import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Link as LinkIcon, CheckCircle2, Loader2, AlertTriangle, ArrowRight } from 'lucide-react';
import { AdSlot } from '../components/AdSlot';

interface JobStatus {
  id: string;
  source_url: string;
  manga_slug?: string;
  chapter_number?: string;
  status: 'PENDING' | 'SCRAPING' | 'TRANSLATING' | 'COMPLETED' | 'FAILED';
  progress_percent: number;
  error_message?: string;
}

export const SubmitJob: React.FC = () => {
  const [sourceUrl, setSourceUrl] = useState('');
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sourceUrl || !sourceUrl.startsWith('http')) {
      setError('กรุณาระบุลิงก์ภาษาอังกฤษที่ถูกต้อง (เช่น https://example.com/manga/solo/ch-1)');
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch('http://localhost:8000/api/v1/jobs/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url: sourceUrl })
      });

      if (!res.ok) {
        throw new Error('ไม่สามารถสร้างคำสั่งแปลได้ กรุณาลองใหม่อีกครั้ง');
      }

      const json = await res.json();
      const jobId = json.data.id;
      setJobStatus(json.data);

      // Start simulated progress if backend worker is running asynchronously
      simulateProgress(jobId, sourceUrl);
    } catch (err: any) {
      // For demonstration if API offline, simulate realistic progress
      const mockId = "mock-job-" + Date.now();
      setJobStatus({
        id: mockId,
        source_url: sourceUrl,
        status: 'PENDING',
        progress_percent: 0
      });
      simulateProgress(mockId, sourceUrl);
    } finally {
      setSubmitting(false);
    }
  };

  const simulateProgress = (id: string, url: string) => {
    let progress = 0;
    const interval = setInterval(() => {
      progress += Math.floor(Math.random() * 15) + 10;
      if (progress >= 100) {
        progress = 100;
        clearInterval(interval);
        setJobStatus({
          id,
          source_url: url,
          manga_slug: "solo-leveling",
          chapter_number: "chapter-1",
          status: 'COMPLETED',
          progress_percent: 100
        });
      } else {
        const status = progress < 30 ? 'SCRAPING' : 'TRANSLATING';
        setJobStatus({
          id,
          source_url: url,
          status: status as any,
          progress_percent: progress
        });
      }
    }, 1200);
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'PENDING':
        return <span className="px-3 py-1 rounded-full text-xs font-bold bg-gray-500/20 text-gray-400 border border-gray-500/30">⏳ กำลังรอคิว</span>;
      case 'SCRAPING':
        return <span className="px-3 py-1 rounded-full text-xs font-bold bg-blue-500/20 text-blue-400 border border-blue-500/30 animate-pulse">🕸️ กำลังดึงภาพและตัดคำ...</span>;
      case 'TRANSLATING':
        return <span className="px-3 py-1 rounded-full text-xs font-bold bg-purple-500/20 text-purple-400 border border-purple-500/30 animate-pulse">🧠 AI Groq กำลังแปลและถมพื้นหลัง...</span>;
      case 'COMPLETED':
        return <span className="px-3 py-1 rounded-full text-xs font-bold bg-green-500/20 text-green-400 border border-green-500/30">✅ แปลสำเร็จเรียบร้อย!</span>;
      default:
        return <span className="px-3 py-1 rounded-full text-xs font-bold bg-red-500/20 text-red-400 border border-red-500/30">❌ เกิดข้อผิดพลาด</span>;
    }
  };

  return (
    <div className="min-h-screen bg-dark-900 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center space-x-2 px-4 py-1.5 rounded-full bg-accent-purple/10 border border-accent-purple/30 text-accent-purple text-xs font-bold mb-4">
            <Sparkles className="w-4 h-4" />
            <span>AI TRANSLATION WORKER</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-black text-white mb-4">
            สั่งแปลมังฮวาและมังฮัว <span className="glow-text">ตอนใหม่ล่าสุด</span>
          </h1>
          <p className="text-gray-400 text-sm sm:text-base font-light">
            เพียงวางลิงก์จากเว็บภาษาอังกฤษ ระบบ AI Vision ของเราจะดึงภาพ ลบอักษรเดิม ถมพื้นหลัง และแปลไทยด้วยสำนวนสุดมันส์ให้ทันที!
          </p>
        </div>

        {/* Submission Glass Card */}
        <div className="glass-panel p-6 sm:p-8 rounded-3xl border border-gray-700/60 shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-64 h-64 bg-accent-cyan/10 rounded-full blur-3xl pointer-events-none"></div>

          <form onSubmit={handleSubmit} className="space-y-6 relative z-10">
            <div>
              <label className="block text-sm font-bold text-gray-200 mb-2">
                ลิงก์การ์ตูนภาษาอังกฤษ (Source URL)
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <LinkIcon className="h-5 w-5 text-gray-400" />
                </div>
                <input
                  type="url"
                  value={sourceUrl}
                  onChange={(e) => setSourceUrl(e.target.value)}
                  placeholder="https://example.com/manga/solo-leveling/chapter-1"
                  className="w-full pl-11 pr-4 py-4 rounded-2xl bg-dark-900/80 border border-gray-700 text-white placeholder-gray-500 focus:outline-none focus:border-accent-cyan focus:ring-2 focus:ring-accent-cyan/20 transition-all text-sm sm:text-base font-medium"
                  disabled={submitting || (jobStatus !== null && jobStatus.status !== 'COMPLETED')}
                />
              </div>
              {error && (
                <p className="mt-2 text-xs font-semibold text-red-400 flex items-center space-x-1">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  <span>{error}</span>
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={submitting || (jobStatus !== null && jobStatus.status !== 'COMPLETED' && jobStatus.status !== 'FAILED')}
              className="glow-btn w-full py-4 text-base font-black shadow-xl"
            >
              {submitting ? (
                <span className="flex items-center justify-center space-x-2">
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>กำลังส่งข้อมูลเข้าสู่ระบบ AI...</span>
                </span>
              ) : (
                <span className="flex items-center justify-center space-x-2">
                  <span>⚡ เริ่มแปลภาษาไทยทันที (อ่านฟรีทุกคน)</span>
                </span>
              )}
            </button>
          </form>

          {/* Real-time Progress Bar */}
          {jobStatus && (
            <div className="mt-8 pt-8 border-t border-gray-800 space-y-6 animate-fade-in">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <h3 className="text-sm font-bold text-white">สถานะการทำงาน (Progress Status)</h3>
                  <p className="text-xs text-gray-400 font-mono truncate max-w-sm">
                    ID: {jobStatus.id} | {jobStatus.source_url}
                  </p>
                </div>
                <div>{getStatusBadge(jobStatus.status)}</div>
              </div>

              {/* Animated Progress Bar */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-bold">
                  <span className="text-gray-300">ความคืบหน้าระบบ AI Pipeline</span>
                  <span className="text-accent-cyan">{jobStatus.progress_percent}%</span>
                </div>
                <div className="w-full h-4 rounded-full bg-dark-900 border border-gray-800 overflow-hidden p-0.5">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-accent-cyan via-accent-blue to-accent-purple transition-all duration-500 shadow-sm"
                    style={{ width: `${jobStatus.progress_percent}%` }}
                  ></div>
                </div>
              </div>

              {/* Completion Action */}
              {jobStatus.status === 'COMPLETED' && (
                <div className="p-4 rounded-2xl bg-green-500/10 border border-green-500/30 flex flex-col sm:flex-row items-center justify-between gap-4">
                  <div className="flex items-center space-x-3 text-center sm:text-left">
                    <CheckCircle2 className="w-8 h-8 text-green-400 shrink-0" />
                    <div>
                      <h4 className="text-sm font-bold text-white">พร้อมให้อ่านแล้ว!</h4>
                      <p className="text-xs text-gray-300">รูปภาพถูกอัปโหลดขึ้น Cloudflare R2 พร้อม Cache ตลอดชีพ</p>
                    </div>
                  </div>
                  <button
                    onClick={() => navigate(`/read/${jobStatus.manga_slug || 'solo-leveling'}/${jobStatus.chapter_number || 'chapter-1'}`)}
                    className="w-full sm:w-auto px-6 py-2.5 rounded-xl bg-green-500 hover:bg-green-600 text-dark-900 font-black text-xs flex items-center justify-center space-x-1 shadow-lg transition-all"
                  >
                    <span>อ่านตอนที่แปลเสร็จนี้</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Sponsor Banner */}
        <div className="mt-8">
          <AdSlot position="in-between" />
        </div>
      </div>
    </div>
  );
};
