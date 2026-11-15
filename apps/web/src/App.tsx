import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import type { PersonaId } from "@alphaforge/api-client";
import { PersonaPicker } from "./PersonaPicker";
import { Chat } from "./Chat";
import { personaById } from "./personas";

// Routes (relative to the Vite base, e.g. /absproxy/5173/):
//   /                 -> redirects to /chat
//   /chat             -> persona picker
//   /chat/:personaId  -> chat with amira | mateo | robert (unknown ids go back to /chat)
export function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<PickerRoute />} />
        <Route path="/chat/:personaId" element={<ChatRoute />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

function PickerRoute() {
  const navigate = useNavigate();
  return <PersonaPicker onPick={(id) => navigate(`/chat/${id}`)} />;
}

function ChatRoute() {
  const { personaId } = useParams();
  const navigate = useNavigate();
  const persona = personaById(personaId);
  if (!persona) return <Navigate to="/chat" replace />;
  const id: PersonaId = persona.id;
  // key: switching persona via the URL starts a fresh chat.
  return <Chat key={id} personaId={id} onBack={() => navigate("/chat")} />;
}
