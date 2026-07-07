import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { BookOpen, PlusCircle, ShieldAlert, Sparkles } from 'lucide-react';

export const Navbar: React.FC = () => {
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  return (
    <header className="sticky top-0 z-50 glass-panel border-b border-gray-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link to="/" className="flex items-center space-x-3 group">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-accent-cyan via-accent-blue to-accent-purple flex items-center justify-center shadow-lg group-hover:scale-105 transition-transform">
              <Sparkles className="w-6 h-6 text-dark-900 animate-pulse" />
            </div>
            <div>
              <span className="text-xl font-black glow-text tracking-wider">
                MANHWA.THAI
              </span>
              <span className="block text-[10px] text-gray-400 font-medium">
                คนแรกสั่งแปล คนต่อไปอ่านฟรี
              </span>
            </div>
          </Link>

          {/* Navigation Links */}
          <nav className="flex items-center space-x-2 sm:space-x-4">
            <Link
              to="/"
              className={`flex items-center space-x-1 sm:space-x-2 px-3 sm:px-4 py-2 rounded-xl text-sm font-semibold transition-all ${
                isActive('/')
                  ? 'bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/30 shadow-sm'
                  : 'text-gray-300 hover:text-white hover:bg-white/5'
              }`}
            >
              <BookOpen className="w-4 h-4" />
              <span>อ่านการ์ตูน</span>
            </Link>

            <Link
              to="/submit"
              className={`flex items-center space-x-1 sm:space-x-2 px-3 sm:px-4 py-2 rounded-xl text-sm font-semibold transition-all ${
                isActive('/submit')
                  ? 'bg-accent-purple/20 text-accent-purple border border-accent-purple/40 shadow-sm'
                  : 'text-gray-300 hover:text-white hover:bg-white/5'
              }`}
            >
              <PlusCircle className="w-4 h-4 text-accent-pink animate-bounce" />
              <span className="bg-gradient-to-r from-accent-pink to-accent-purple bg-clip-text text-transparent font-bold">
                สั่งแปลตอนใหม่
              </span>
            </Link>

            <Link
              to="/admin"
              className={`flex items-center space-x-1 sm:space-x-2 px-3 py-2 rounded-xl text-xs sm:text-sm font-medium transition-all ${
                isActive('/admin')
                  ? 'bg-red-500/20 text-red-400 border border-red-500/40'
                  : 'text-gray-400 hover:text-red-400 hover:bg-red-500/10'
              }`}
            >
              <ShieldAlert className="w-4 h-4" />
              <span className="hidden sm:inline">ผู้ดูแลระบบ</span>
            </Link>
          </nav>
        </div>
      </div>
    </header>
  );
};
