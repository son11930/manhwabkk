import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Navbar } from './components/Navbar';
import { Home } from './pages/Home';
import { Reader } from './pages/Reader';
import { SubmitJob } from './pages/SubmitJob';
import { Admin } from './pages/Admin';

export const App: React.FC = () => {
  return (
    <Router>
      <div className="min-h-screen bg-dark-900 text-gray-100 flex flex-col font-sans selection:bg-accent-cyan selection:text-dark-900">
        <Navbar />
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/read/:seriesSlug/:chapterNum" element={<Reader />} />
            <Route path="/submit" element={<SubmitJob />} />
            <Route path="/admin" element={<Admin />} />
          </Routes>
        </main>
        
        {/* Footer */}
        <footer className="glass-panel border-t border-gray-800 py-8 text-center text-xs text-gray-500">
          <div className="max-w-7xl mx-auto px-4 space-y-2">
            <p className="font-bold text-gray-400">MANHWA.THAI - AI Manga & Manhua Translation Platform</p>
            <p>"คนแรกสั่งแปล คนต่อไปอ่านฟรี!" Powered by Cloudflare R2 Immutable Storage & Groq LLM</p>
            <p className="text-[10px] text-gray-600">สงวนสิทธิ์ผู้ดูแลระบบสูงสุด (Super Admin Restricted Area)</p>
          </div>
        </footer>
      </div>
    </Router>
  );
};

export default App;
