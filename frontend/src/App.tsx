import { Routes, Route } from "react-router-dom";
import { Feed } from "./views/Feed";
import { Recorder } from "./views/Recorder";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Feed />} />
      <Route path="/record" element={<Recorder />} />
    </Routes>
  );
}
