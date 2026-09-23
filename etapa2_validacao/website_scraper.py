"""Scraper de contato: extrai email e/ou URL de formulário de contato de
um website já confirmado pela etapa2_validacao/places_discovery.py.

Estratégia (inspirada na abordagem do omkarcloud/website-email-contact-scraper,
sem reuso de código):
1. Tenta requests (httpx) + BeautifulSoup na home. Cobre a maioria dos
   sites institucionais estáticos.
2. Se a página renderizar praticamente vazia (sinal de SPA/JS-heavy),
   cai para Playwright para renderizar o JS antes de extrair.
3. Se não achar email/formulário na home, tenta páginas de contato/sobre
   conhecidas (por link ou por caminho convencional).

Deobfuscação de email suportada:
- mailto: links
- Cloudflare Email Protection (`data-cfemail`, decodificação XOR)
- ofuscação textual tipo "fulano [at] empresa [dot] com" / "(arroba)"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
PLAYWRIGHT_TIMEOUT_MS = 20000

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

CAMINHOS_CONTATO = [
    "contato",
    "contact",
    "fale-conosco",
    "fale_conosco",
    "faleconosco",
    "sobre",
    "about",
    "sobre-nos",
    "quem-somos",
]

# Regex "prática" de email: local-part sem "/" ou "*" (evita engolir
# caminho de URL ou email mascarado com asterisco) e domínio terminando
# em TLD só-letras (evita casar número de versão de pacote npm, ex.:
# "bootstrap@5.0.0-beta3", "aos@2.3.1").
_EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)

_EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")

_PALAVRAS_CHAVE_FORMULARIO = ["contato", "contact", "mensagem", "message", "fale conosco", "envie"]

# Domínios de infraestrutura/telemetria que aparecem no HTML/JS de sites
# mas nunca são um contato de verdade (Sentry DSN embutido, CDN, analytics).
_DOMINIOS_BLOQUEADOS = (
    "sentry.io",
    "sentry-next",
    "wixpress.com",
    "bugsnag.com",
    "rollbar.com",
    "googletagmanager.com",
    "google-analytics.com",
    "doubleclick.net",
    "hotjar.com",
    "cloudflareinsights.com",
)

# Placeholders óbvios de template/widget, não são contato real.
_ENDERECOS_PLACEHOLDER = (
    "visitor@email.com",
    "seuemail@",
    "seu-email@",
    "nome@email.com",
    "email@email.com",
    "user@example.com",
    "name@example.com",
)
_DOMINIOS_PLACEHOLDER = (
    "example.com",
    "exemplo.com",
    "exemplo.com.br",
    "test.com",
    "domain.com",
    "email.com",
    "email.com.br",
    "seudominio.com",
    "seudominio.com.br",
)


def _email_valido(candidato: str) -> bool:
    """Filtro final aplicado a QUALQUER candidato a email, não importa a
    origem (mailto:, data-cfemail ou texto visível) — mailto: em particular
    não passa pelo regex, então sem esse filtro um href tipo
    `mailto:co*********@***.com.br` (email mascarado de propósito no
    próprio site) entraria como válido."""
    if not candidato or "*" in candidato:
        return False
    if not _EMAIL_REGEX.fullmatch(candidato):
        return False
    candidato_lower = candidato.lower()
    if candidato_lower in _ENDERECOS_PLACEHOLDER:
        return False
    dominio = candidato_lower.rsplit("@", 1)[-1]
    if dominio in _DOMINIOS_PLACEHOLDER:
        return False
    if any(bloqueado in dominio for bloqueado in _DOMINIOS_BLOQUEADOS):
        return False
    return True


@dataclass
class ResultadoScraping:
    site_ativo: bool
    email: Optional[str] = None
    formulario_contato_url: Optional[str] = None
    paginas_verificadas: list = field(default_factory=list)
    erro: Optional[str] = None

    @property
    def tem_pelo_menos_um_canal(self) -> bool:
        return bool(self.email or self.formulario_contato_url)


def _decodificar_cfemail(cfemail_hex: str) -> Optional[str]:
    """Decodifica e-mail ofuscado pelo Cloudflare Email Protection.

    Formato: primeiro byte é a chave XOR aplicada a todos os demais bytes.
    """
    try:
        raw = bytes.fromhex(cfemail_hex)
    except ValueError:
        return None
    if not raw:
        return None
    key = raw[0]
    decoded = bytes(b ^ key for b in raw[1:])
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _desofuscar_texto(texto: str) -> str:
    """Reverte ofuscações textuais comuns: [at]/(at)/arroba, [dot]/(dot)/ponto."""
    t = texto
    t = re.sub(r"\s*[\(\[]\s*at\s*[\)\]]\s*", "@", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[\(\[]\s*arroba\s*[\)\]]\s*", "@", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[\(\[]\s*dot\s*[\)\]]\s*", ".", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[\(\[]\s*ponto\s*[\)\]]\s*", ".", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+@\s+", "@", t)
    t = re.sub(r"\s+\.\s+", ".", t)
    return t


def _extrair_emails_de_html(html: str) -> list[str]:
    """Extrai candidatos a email de mailto:, Cloudflare Email Protection e
    texto visível (nunca do HTML/JS bruto — scripts de terceiros como
    CDN/analytics/Sentry produzem falsos positivos no formato "email").

    Todo candidato, seja qual for a origem, passa por `_email_valido`
    antes de entrar no resultado.
    """
    soup = BeautifulSoup(html, "html.parser")

    candidatos: set[str] = set()

    for link in soup.select('a[href^="mailto:"]'):
        endereco = link["href"].split(":", 1)[1].split("?", 1)[0].strip()
        if endereco:
            candidatos.add(endereco)

    for el in soup.select("[data-cfemail]"):
        decodificado = _decodificar_cfemail(el["data-cfemail"])
        if decodificado:
            candidatos.add(decodificado)

    # formsubmit.co é um serviço real de form-to-email sem backend: a URL
    # de action embute o email de destino de verdade (ex.:
    # "https://formsubmit.co/contato@empresa.com.br"). Extrai
    # especificamente desse padrão de atributo, não do HTML bruto em geral.
    for form in soup.find_all("form", action=True):
        action = form["action"]
        if "formsubmit.co/" in action.lower():
            possivel_email = action.split("formsubmit.co/", 1)[-1].split("?", 1)[0].strip()
            if possivel_email:
                candidatos.add(possivel_email)

    # remove script/style antes de ler texto visível: evita casar emails
    # falsos dentro de bundles JS (URLs de CDN, DSN de telemetria, etc.)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    texto_visivel = _desofuscar_texto(soup.get_text(" ", strip=True))
    for match in _EMAIL_REGEX.findall(texto_visivel):
        if not match.lower().endswith(_EXTENSOES_IMAGEM):
            candidatos.add(match)

    emails = {c for c in candidatos if _email_valido(c)}
    return sorted(emails)


def _parece_formulario_contato(form_tag, url_pagina: str) -> bool:
    # action apontando pra um serviço de form-to-email é sinal forte e
    # independente de contato real, mesmo sem nenhuma palavra-chave por perto.
    if "formsubmit.co/" in (form_tag.get("action") or "").lower():
        return True

    campos = form_tag.find_all(["input", "textarea"])
    tem_campo_texto_livre = any(
        (c.name == "textarea") or (c.get("type") in (None, "text", "email"))
        for c in campos
    )
    classes = form_tag.get("class") or []
    contexto = " ".join(
        [
            url_pagina.lower(),
            (form_tag.get("id") or "").lower(),
            " ".join(classes).lower(),
            form_tag.get_text(" ", strip=True).lower(),
        ]
    )
    return tem_campo_texto_livre and any(p in contexto for p in _PALAVRAS_CHAVE_FORMULARIO)


class WebsiteScraper:
    def __init__(
        self,
        usar_playwright_fallback: bool = True,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_paginas_contato: int = 5,
    ):
        self._usar_playwright = usar_playwright_fallback
        self._timeout = timeout
        self._max_paginas_contato = max_paginas_contato

    def _buscar_html_estatico(self, url: str) -> Optional[str]:
        headers = {"User-Agent": USER_AGENT}
        try:
            with httpx.Client(timeout=self._timeout, headers=headers, follow_redirects=True) as client:
                resp = client.get(url)
            if resp.status_code >= 400:
                return None
            return resp.text
        except httpx.HTTPError:
            return None

    def _buscar_html_playwright(self, url: str) -> Optional[str]:
        """Fallback para sites JS-heavy (SPA). Requer `playwright install chromium`."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page(user_agent=USER_AGENT)
                    page.goto(url, timeout=PLAYWRIGHT_TIMEOUT_MS, wait_until="networkidle")
                    html = page.content()
                finally:
                    browser.close()
            return html
        except Exception:
            return None

    def _pagina_parece_vazia(self, html: Optional[str]) -> bool:
        if not html:
            return True
        texto = BeautifulSoup(html, "html.parser").get_text(strip=True)
        return len(texto) < 200

    def _obter_html(self, url: str) -> Optional[str]:
        html = self._buscar_html_estatico(url)
        if self._usar_playwright and self._pagina_parece_vazia(html):
            html_renderizado = self._buscar_html_playwright(url)
            if html_renderizado:
                html = html_renderizado
        return html

    def _descobrir_links_contato(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            texto = a.get_text(" ", strip=True).lower()
            href_lower = href.lower()
            if any(caminho in href_lower for caminho in CAMINHOS_CONTATO) or any(
                palavra in texto for palavra in ("contato", "contact", "fale conosco")
            ):
                links.add(urljoin(base_url, href))

        # garante que caminhos convencionais sejam tentados mesmo sem link visível
        for caminho in CAMINHOS_CONTATO:
            links.add(urljoin(base_url + "/", caminho))

        base_dominio = urlparse(base_url).netloc
        return [link for link in links if urlparse(link).netloc == base_dominio]

    def _checar_formulario(self, html: str, url_pagina: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        for form in soup.find_all("form"):
            if _parece_formulario_contato(form, url_pagina):
                return url_pagina
        return None

    def extrair_contato(self, website_url: str) -> ResultadoScraping:
        paginas_verificadas: list[str] = []

        html_home = self._obter_html(website_url)
        if html_home is None:
            return ResultadoScraping(site_ativo=False, erro="site_inacessivel")

        paginas_verificadas.append(website_url)

        emails = _extrair_emails_de_html(html_home)
        formulario_url = self._checar_formulario(html_home, website_url)

        if not emails or not formulario_url:
            for link in self._descobrir_links_contato(html_home, website_url)[: self._max_paginas_contato]:
                if link in paginas_verificadas:
                    continue
                html_pagina = self._obter_html(link)
                paginas_verificadas.append(link)
                if not html_pagina:
                    continue
                if not emails:
                    emails = _extrair_emails_de_html(html_pagina)
                if not formulario_url:
                    formulario_url = self._checar_formulario(html_pagina, link)
                if emails and formulario_url:
                    break

        return ResultadoScraping(
            site_ativo=True,
            email=emails[0] if emails else None,
            formulario_contato_url=formulario_url,
            paginas_verificadas=paginas_verificadas,
        )
