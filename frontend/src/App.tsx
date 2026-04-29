import { Routes, Route, Navigate } from "react-router-dom";
import { Feed } from "./views/Feed";
import { Montage } from "./views/Montage";
import { Recorder } from "./views/Recorder";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Recorder />} />
      <Route path="/feed" element={<Feed />} />
      <Route path="/m/:segmentId" element={<Montage />} />
      <Route path="/record" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
