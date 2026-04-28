import { Routes, Route, Navigate } from "react-router-dom";
import { Analytics } from "@vercel/analytics/react";
import { Feed } from "./views/Feed";
import { Recorder } from "./views/Recorder";

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<Recorder />} />
        <Route path="/feed" element={<Feed />} />
        <Route path="/record" element={<Navigate to="/" replace />} />
      </Routes>
      <Analytics />
    </>
  );
}
