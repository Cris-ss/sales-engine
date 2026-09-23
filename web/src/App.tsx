import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ToastProvider } from "./components/states";
import { KanbanPage } from "./features/kanban/KanbanPage";
import { LeadDetailDrawer } from "./features/leads/LeadDetailDrawer";
import { LeadListPage } from "./features/leads/LeadListPage";
import { MapPage } from "./features/map/MapPage";
import { MetricsPage } from "./features/metrics/MetricsPage";
import { ProspeccaoPage } from "./features/prospeccao/ProspeccaoPage";
import { SistemaPage } from "./features/sistema/SistemaPage";
import { WhatsappPage } from "./features/whatsapp/WhatsappPage";

export default function App() {
  return (
    <ToastProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<LeadListPage />} />
          <Route path="/kanban" element={<KanbanPage />} />
          <Route path="/mapa" element={<MapPage />} />
          <Route path="/metricas" element={<MetricsPage />} />
          <Route path="/prospeccao" element={<ProspeccaoPage />} />
          <Route path="/whatsapp" element={<WhatsappPage />} />
          <Route path="/sistema" element={<SistemaPage />} />
          <Route path="*" element={<p className="estado">Página não encontrada.</p>} />
        </Routes>
        <LeadDetailDrawer />
      </AppShell>
    </ToastProvider>
  );
}
