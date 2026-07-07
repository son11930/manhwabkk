import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight, List, Home as HomeIcon } from 'lucide-react';
import { AdSlot } from '../components/AdSlot';

interface PageItem {
  id: string;
  page_index: number;
  image_url: string;
}

interface ChapterData {
  id: string;
  series_id: string;
  chapter_number: string;
  title_th?: string;
  source_url: string;
  next_chapter_url?: string;
  prev_chapter_url?: string;
  pages: PageItem[];
}

export const Reader: React.FC = () => {
  const { seriesSlug, chapterNum } = useParams<{ seriesSlug: string; chapterNum: string }>();
  const [chapter, setChapter] = useState<ChapterData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // Fallback mock data for demonstration
  const fallbackChapter: ChapterData = {
    id: `mock-${seriesSlug}-${chapterNum}`,
    series_id: seriesSlug || "mock-series",
    chapter_number: chapterNum || "chapter-1",
    title_th: `ตอนที่ ${chapterNum?.replace(/[^0-9]/g, '') || "1"} : แปลไทยฉบับ AI Vision (${seriesSlug?.replace(/-/g, ' ').toUpperCase() || 'MANHWA'})`,
    source_url: "https://example.com",
    next_chapter_url: `/read/${seriesSlug || 'manga'}/chapter-${(Number(chapterNum?.replace(/[^0-9]/g, '') || 1) + 1)}`,
    prev_chapter_url: `/read/${seriesSlug || 'manga'}/chapter-${Math.max(1, (Number(chapterNum?.replace(/[^0-9]/g, '') || 1) - 1))}`,
    pages: [
      { id: "p1", page_index: 1, image_url: "https://images.unsplash.com/photo-1578632767115-351597cf2477?q=80&w=800&auto=format&fit=crop" },
      { id: "p2", page_index: 2, image_url: "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?q=80&w=800&auto=format&fit=crop" },
      { id: "p3", page_index: 3, image_url: "https://images.unsplash.com/photo-1563089145-599997674d42?q=80&w=800&auto=format&fit=crop" },
      { id: "p4", page_index: 4, image_url: "https://images.unsplash.com/photo-1578632767115-351597cf2477?q=80&w=800&auto=format&fit=crop" },
    ]
  };

  useEffect(() => {
    window.scrollTo(0, 0);
    const fetchChapter = async () => {
      setLoading(true);
      try {
        const res = await fetch(`http://localhost:8000/api/v1/series/${seriesSlug}/chapters/${chapterNum}`);
        if (res.ok) {
          const json = await res.json();
          if (json.data) {
            setChapter(json.data);
          } else {
            setChapter(fallbackChapter);
          }
        } else {
          setChapter(fallbackChapter);
        }
      } catch (err) {
        setChapter(fallbackChapter);
      } finally {
        setLoading(false);
      }
    };
    fetchChapter();
  }, [seriesSlug, chapterNum]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-dark-900">
        <div className="flex flex-col items-center space-y-4">
          <div className="w-12 h-12 border-4 border-accent-cyan border-t-transparent rounded-full animate-spin"></div>
          <span className="text-gray-400 font-medium">กำลังโหลดภาพจาก Cloudflare R2...</span>
        </div>
      </div>
    );
  }

  const currentChapter = chapter || fallbackChapter;

  return (
    <div className="min-h-screen bg-dark-900 pb-24">
      {/* Sticky Reader Bar */}
      <div className="sticky top-16 z-40 bg-dark-800/90 backdrop-blur-md border-b border-gray-800 py-3 px-4 sm:px-8">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Link to="/" className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white transition-colors">
              <HomeIcon className="w-5 h-5" />
            </Link>
            <div>
              <h1 className="text-sm sm:text-base font-bold text-white line-clamp-1">
                {seriesSlug?.replace('-', ' ').toUpperCase()} - {currentChapter.chapter_number}
              </h1>
              <span className="text-xs text-gray-400 font-light block">
                {currentChapter.title_th}
              </span>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            {currentChapter.prev_chapter_url && (
              <Link
                to={currentChapter.prev_chapter_url.startsWith('http') ? '#' : currentChapter.prev_chapter_url}
                className="p-2 sm:px-3 sm:py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 font-semibold text-xs flex items-center space-x-1"
              >
                <ChevronLeft className="w-4 h-4" />
                <span className="hidden sm:inline">ตอนก่อนหน้า</span>
              </Link>
            )}
            {currentChapter.next_chapter_url && (
              <Link
                to={currentChapter.next_chapter_url.startsWith('http') ? '#' : currentChapter.next_chapter_url}
                className="p-2 sm:px-3 sm:py-1.5 rounded-xl bg-accent-cyan text-dark-900 font-bold text-xs flex items-center space-x-1 hover:bg-accent-cyan/80 transition-all"
              >
                <span className="hidden sm:inline">ตอนต่อไป</span>
                <ChevronRight className="w-4 h-4" />
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Main Responsive Reader Layout */}
      <div className="max-w-7xl mx-auto flex justify-center pt-4 sm:pt-6 px-0 sm:px-4 gap-6">
        {/* Left/Main Column: Vertical Webtoon Stream (No borders on mobile for immersive reading) */}
        <div className="w-full max-w-[800px] flex flex-col items-center bg-dark-900 sm:bg-dark-800/40 sm:rounded-2xl sm:border sm:border-gray-800 sm:p-4 sm:shadow-2xl overflow-hidden">
          {/* Top Monetization Banner */}
          <AdSlot position="top" />

          {/* Image Stream */}
          <div className="w-full flex flex-col items-center space-y-0 sm:space-y-1 my-4">
            {currentChapter.pages.map((page, index) => (
              <React.Fragment key={page.id || index}>
                <img
                  src={page.image_url}
                  alt={`Page ${page.page_index}`}
                  loading="lazy"
                  className="w-full max-w-full h-auto object-contain select-none shadow-md sm:rounded-lg"
                />
                
                {/* Inter-page Monetization Ad every 2 pages */}
                {(index + 1) % 2 === 0 && (
                  <div className="w-full py-4 px-2">
                    <AdSlot position="in-between" />
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>

          {/* Bottom Monetization Banner before Next Chapter */}
          <AdSlot position="bottom" />

          {/* Bottom Chapter Navigation Bar */}
          <div className="w-full p-6 mt-6 rounded-2xl bg-dark-800 border border-gray-700/60 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="text-center sm:text-left">
              <h3 className="text-base font-bold text-white">อ่านตอนจบเรียบร้อยแล้ว!</h3>
              <p className="text-xs text-gray-400">สนับสนุนเซิร์ฟเวอร์โดยการคลิกป้ายโฆษณาด้านบน</p>
            </div>

            <div className="flex items-center space-x-3 w-full sm:w-auto">
              {currentChapter.prev_chapter_url && (
                <Link
                  to={currentChapter.prev_chapter_url.startsWith('http') ? '#' : currentChapter.prev_chapter_url}
                  className="flex-1 sm:flex-initial px-4 py-3 rounded-xl bg-white/10 hover:bg-white/15 text-white font-bold text-sm text-center flex items-center justify-center space-x-1"
                >
                  <ChevronLeft className="w-4 h-4" />
                  <span>ตอนก่อนหน้า</span>
                </Link>
              )}
              {currentChapter.next_chapter_url && (
                <Link
                  to={currentChapter.next_chapter_url.startsWith('http') ? '#' : currentChapter.next_chapter_url}
                  className="flex-1 sm:flex-initial px-6 py-3 rounded-xl bg-gradient-to-r from-accent-cyan to-accent-blue text-dark-900 font-black text-sm text-center flex items-center justify-center space-x-1 shadow-lg hover:shadow-accent-cyan/50 transition-all"
                >
                  <span>อ่านตอนต่อไป</span>
                  <ChevronRight className="w-4 h-4" />
                </Link>
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Desktop Sidebar & VIP Monetization */}
        <aside className="hidden lg:flex w-80 flex-col space-y-6 shrink-0 sticky top-32 h-fit">
          <div className="glass-panel p-6 rounded-2xl border border-gray-800">
            <h3 className="text-lg font-bold text-white mb-3 flex items-center space-x-2">
              <List className="w-5 h-5 text-accent-cyan" />
              <span>สารบัญตอนทั้งหมด</span>
            </h3>
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {["chapter-1", "chapter-2", "chapter-3", "chapter-4", "chapter-5"].map((ch) => (
                <Link
                  key={ch}
                  to={`/read/${seriesSlug}/${ch}`}
                  className={`block px-3 py-2 rounded-xl text-sm font-semibold transition-all ${
                    ch === currentChapter.chapter_number
                      ? 'bg-accent-cyan/20 text-accent-cyan border border-accent-cyan/40'
                      : 'text-gray-400 hover:text-white hover:bg-white/5'
                  }`}
                >
                  {ch.toUpperCase()} : ตอนล่าสุด
                </Link>
              ))}
            </div>
          </div>

          {/* Desktop Sidebar Ad */}
          <AdSlot position="sidebar" />
        </aside>
      </div>
    </div>
  );
};
