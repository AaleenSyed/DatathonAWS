import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { PersonaPicker } from "./PersonaPicker";
import { ProfileBuilder } from "./ProfileBuilder";
import { Chat } from "./Chat";
import { isCustomId, personaById } from "./personas";

// Routes (relative to the Vite base, e.g. /absproxy/5173/):
//   /                 -> redirects to /chat
//   /chat             -> persona picker
//   /profile          -> "Build my own profile" questionnaire
//   /chat/:personaId  -> chat with amira | mateo | robert | custom-<8 chars> (unknown ids go back to /chat)
export function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<PickerRoute />} />
        <Route path="/profile" element={<BuilderRoute />} />
        <Route path="/chat/:personaId" element={<ChatRoute />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

function PickerRoute() {
  const navigate = useNavigate();
  return <PersonaPicker onPick={(id) => navigate(`/chat/${id}`)} onBuild={() => navigate("/profile")} />;
}

function BuilderRoute() {
  const navigate = useNavigate();
  return <ProfileBuilder onStart={(id) => navigate(`/chat/${id}`)} onBack={() => navigate("/chat")} />;
}

function ChatRoute() {
  const { personaId } = useParams();
  const navigate = useNavigate();
  const id = isCustomId(personaId) ? personaId : personaById(personaId)?.id;
  if (!id) return <Navigate to="/chat" replace />;
  // key: switching persona via the URL starts a fresh chat.
  return <Chat key={id} personaId={id} onBack={() => navigate(isCustomId(id) ? "/profile" : "/chat")} />;
}
