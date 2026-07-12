import React from 'react';
import { ExternalLink, DollarSign } from 'lucide-react';

interface AdSlotProps {
  position?: 'top' | 'bottom' | 'in-between' | 'sidebar';
  className?: string;
}

export const AdSlot: React.FC<AdSlotProps> = ({ position = 'in-between', className = '' }) => {
  const getBannerContent = () => {
    switch (position) {
      case 'top':
        return {
          title: "🚀 สนับสนุนเซิร์ฟเวอร์อ่านฟรีไม่มีสะดุด!",
          desc: "คลิกชมสินค้าสนับสนุนค่าเช่าเซิร์ฟเวอร์ Cloudflare R2 ของเรา",
          badge: "ADVERTISER SPONSOR",
          height: "h-24 sm:h-28"
        };
      case 'bottom':
        return {
          title: "🔥 เกมมือถือแนวมันฮวายอดฮิตอันดับ 1",
          desc: "ลงทะเบียนล่วงหน้าวันนี้ รับไอเทมระดับ SS ทันที!",
          badge: "FEATURED AD",
          height: "h-28 sm:h-32"
        };
      case 'sidebar':
        return {
          title: "💎 สมัครสมาชิก VIP",
          desc: "อ่านล่วงหน้าก่อนใคร ไม่เห็นป้ายโฆษณาตลอดชีพ",
          badge: "VIP BENEFIT",
          height: "h-64 sm:h-80 flex-col text-center"
        };
      case 'in-between':
      default:
        return {
          title: "⚡ โฆษณาสนับสนุนค่าแปล AI & ค่าเซิร์ฟเวอร์",
          desc: "คนแรกสั่งแปล คนต่อไปอ่านฟรี! ขอขอบคุณทุกท่านที่ช่วยคลิกสนับสนุน",
          badge: "SERVER SUPPORT",
          height: "h-20 sm:h-24"
        };
    }
  };

  const ad = getBannerContent();

  return (
    <div className={`my-4 w-full px-2 ${className}`}>
      <div
        className={`relative overflow-hidden rounded-2xl p-4 sm:p-6 border border-dashed border-gray-600/60 bg-gradient-to-r from-dark-800 via-dark-800/90 to-dark-900 flex items-center justify-between group cursor-pointer hover:border-accent-cyan/80 transition-all duration-300 shadow-lg ${ad.height}`}
      >
        {/* Animated Glow Overlay */}
        <div className="absolute -right-10 -top-10 w-32 h-32 bg-accent-cyan/10 rounded-full blur-2xl group-hover:bg-accent-purple/20 transition-all"></div>
        
        <div className="flex items-center space-x-3 sm:space-x-4 z-10">
          <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 border border-amber-500/30 flex items-center justify-center shrink-0">
            <DollarSign className="w-5 h-5 sm:w-6 sm:h-6 text-amber-400" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-[10px] sm:text-xs font-bold tracking-widest px-2 py-0.5 rounded-full bg-white/10 text-accent-cyan border border-white/10">
                {ad.badge}
              </span>
              <span className="text-[10px] text-gray-400">Sponsored</span>
            </div>
            <h4 className="text-sm sm:text-base font-bold text-white mt-1 group-hover:text-accent-cyan transition-colors">
              {ad.title}
            </h4>
            <p className="text-xs sm:text-sm text-gray-400 max-w-md line-clamp-1">
              {ad.desc}
            </p>
          </div>
        </div>

        <div className="hidden sm:flex items-center space-x-2 px-4 py-2 rounded-xl bg-white/5 border border-white/10 group-hover:bg-accent-cyan group-hover:text-dark-900 font-bold text-xs transition-all z-10">
          <span>เยี่ยมชม</span>
          <ExternalLink className="w-3.5 h-3.5" />
        </div>
      </div>
    </div>
  );
};
