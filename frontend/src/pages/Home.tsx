import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, Clock, ArrowRight, TrendingUp } from 'lucide-react';
import { AdSlot } from '../components/AdSlot';

interface SeriesItem {
  id: string;
  slug: string;
  title_th: string;
  title_en?: string;
  cover_image_url?: string;
  description?: string;
  created_at: string;
  latest_chapter?: string;
}

export const Home: React.FC = () => {
  const [seriesList, setSeriesList] = useState<SeriesItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  // Mock initial data if backend is empty or loading
  const fallbackSeries: SeriesItem[] = [
    {
      id: "1",
      slug: "solo-leveling",
      title_th: "โซโลเลเวลลิ่ง (Solo Leveling)",
      title_en: "Solo Leveling",
      cover_image_url: "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?q=80&w=600&auto=format&fit=crop",
      description: "เมื่อฮันเตอร์ระดับ E ที่อ่อนแอที่สุดในโลก ได้รับระบบลับที่สามารถอัปเกรดเลเวลได้เพียงคนเดียวในโลก!",
      created_at: new Date().toISOString(),
      latest_chapter: "chapter-1"
    },
    {
      id: "2",
      slug: "omniscient-reader",
      title_th: "อ่านชะตาวันสิ้นโลก (Omniscient Reader)",
      title_en: "Omniscient Reader's Viewpoint",
      cover_image_url: "https://images.unsplash.com/photo-1578632767115-351597cf2477?q=80&w=600&auto=format&fit=crop",
      description: "นิยายที่เขาอ่านมา 10 ปี กลายเป็นความจริงในวันสิ้นโลก มีเพียงเขาเท่านั้นที่รู้ตอนจบ!",
      created_at: new Date().toISOString(),
      latest_chapter: "chapter-15"
    },
    {
      id: "3",
      slug: "nano-machine",
      title_th: "นาโนแมชชีน (Nano Machine)",
      title_en: "Nano Machine",
      cover_image_url: "https://images.unsplash.com/photo-1563089145-599997674d42?q=80&w=600&auto=format&fit=crop",
      description: "เมื่อลูกหลานจากอนาคตส่งสุดยอดนาโนแมชชีนมาฝังในร่างขององค์ชายแห่งพรรคมาร!",
      created_at: new Date().toISOString(),
      latest_chapter: "chapter-42"
    }
  ];

  useEffect(() => {
    const fetchSeries = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/v1/series');
        if (res.ok) {
          const json = await res.json();
          if (json.data && json.data.length > 0) {
            setSeriesList(json.data);
          } else {
            setSeriesList(fallbackSeries);
          }
        } else {
          setSeriesList(fallbackSeries);
        }
      } catch (err) {
        // Use fallback on fetch failure
        setSeriesList(fallbackSeries);
      } finally {
        setLoading(false);
      }
    };
    fetchSeries();
  }, []);

  return (
    <div className="min-h-screen pb-16">
      {/* Hero Banner Section */}
      <section className="relative overflow-hidden py-16 sm:py-24 border-b border-gray-800">
        <div className="absolute inset-0 bg-gradient-to-b from-accent-purple/10 via-dark-900 to-dark-900 z-0"></div>
        <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-accent-cyan/15 blur-[120px] rounded-full pointer-events-none"></div>
        
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10 text-center">
          <div className="inline-flex items-center space-x-2 px-4 py-1.5 rounded-full bg-white/5 border border-white/10 text-accent-cyan text-xs font-bold mb-6 backdrop-blur-md animate-pulse">
            <Sparkles className="w-4 h-4" />
            <span>AI TRANSLATION PLATFORM สำหรับคนรักการ์ตูน</span>
          </div>
          <h1 className="text-4xl sm:text-6xl font-black tracking-tight text-white mb-6">
            คนแรกสั่งแปล <span className="glow-text">คนต่อไปอ่านฟรี!</span>
          </h1>
          <p className="text-base sm:text-lg text-gray-300 max-w-2xl mx-auto mb-8 font-light leading-relaxed">
            ระบบแปลมังฮวาและมังฮัวจากภาษาอังกฤษเป็นไทยอัตโนมัติด้วย AI (Groq + Vision Pipeline) 
            ลบอักษรเดิม ถมขาว และจัดหน้าแปลไทยเนียนกริบ ภายใน 60 วินาที
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link to="/submit" className="glow-btn w-full sm:w-auto text-center">
              <span className="mr-2">⚡</span> สั่งแปลตอนใหม่ทันที
            </Link>
            <a href="#popular" className="px-6 py-3 rounded-xl bg-white/10 hover:bg-white/15 text-white font-bold transition-all border border-white/10 w-full sm:w-auto text-center">
              📚 ดูเรื่องที่แปลแล้ว
            </a>
          </div>
        </div>
      </section>

      {/* Monetization Top Ad */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <AdSlot position="top" />
      </div>

      {/* Main Catalog Grid */}
      <main id="popular" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-12">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-accent-cyan/20 flex items-center justify-center border border-accent-cyan/30">
              <TrendingUp className="w-5 h-5 text-accent-cyan" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-white">มังฮวายอดนิยมล่าสุด</h2>
              <p className="text-xs text-gray-400">อัปเดตแบบเรียลไทม์จากระบบแปล AI</p>
            </div>
          </div>
          <span className="text-xs font-semibold text-accent-cyan bg-accent-cyan/10 px-3 py-1.5 rounded-full border border-accent-cyan/20">
            ทั้งหมด {seriesList.length} เรื่อง
          </span>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 animate-pulse">
            {[1, 2, 3].map((n) => (
              <div key={n} className="h-80 rounded-2xl bg-dark-800 border border-gray-800"></div>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {seriesList.map((series) => (
              <div key={series.id} className="glass-card rounded-2xl overflow-hidden flex flex-col justify-between group">
                <div className="relative h-56 overflow-hidden">
                  <img
                    src={series.cover_image_url || "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?q=80&w=600&auto=format&fit=crop"}
                    alt={series.title_th}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-dark-900 via-dark-900/40 to-transparent"></div>
                  <span className="absolute top-3 right-3 px-3 py-1 rounded-full text-xs font-bold bg-accent-cyan/90 text-dark-900 shadow-lg backdrop-blur-md">
                    ⚡ อ่านฟรี
                  </span>
                  <div className="absolute bottom-3 left-3 right-3">
                    <h3 className="text-lg font-bold text-white group-hover:text-accent-cyan transition-colors line-clamp-1">
                      {series.title_th}
                    </h3>
                    {series.title_en && (
                      <span className="text-xs text-gray-400 font-medium block">
                        {series.title_en}
                      </span>
                    )}
                  </div>
                </div>

                <div className="p-4 flex-1 flex flex-col justify-between">
                  <p className="text-sm text-gray-300 line-clamp-2 mb-4 font-light">
                    {series.description || "ยังไม่มีรายละเอียดเรื่องย่อสำหรับมังฮวาเรื่องนี้..."}
                  </p>

                  <div className="flex items-center justify-between pt-3 border-t border-white/10">
                    <div className="flex items-center space-x-1 text-xs text-gray-400">
                      <Clock className="w-3.5 h-3.5 text-accent-purple" />
                      <span>อัปเดตล่าสุด: ตอนที่ {series.latest_chapter || "1"}</span>
                    </div>
                    
                    <Link
                      to={`/read/${series.slug}/${series.latest_chapter || "chapter-1"}`}
                      className="inline-flex items-center space-x-1 px-4 py-2 rounded-xl bg-accent-blue/20 hover:bg-accent-blue text-accent-blue hover:text-white font-bold text-xs transition-all border border-accent-blue/30"
                    >
                      <span>อ่านตอนล่าสุด</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </Link>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Monetization Bottom Ad */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-16">
        <AdSlot position="bottom" />
      </div>
    </div>
  );
};
