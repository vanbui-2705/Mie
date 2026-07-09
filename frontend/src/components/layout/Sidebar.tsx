"use client";

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Users, MessageSquare, Send, Share2, Settings } from 'lucide-react';
import { cn } from '@/lib/utils';

const navItems = [
  { name: 'Quản lý Profile', href: '/', icon: Users },
  { name: 'Auto Comment', href: '/auto-comment', icon: MessageSquare },
  { name: 'Auto Đăng Bài', href: '/auto-post', icon: Send },
  { name: 'Auto Share Nhóm', href: '/auto-share', icon: Share2 },
  { name: 'Quản lý Proxy & Cấu hình', href: '/proxies', icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-[250px] bg-gray-900 text-gray-300 flex flex-col h-screen shrink-0 border-r border-gray-800 shadow-xl z-20">
      <div className="h-16 flex items-center px-6 border-b border-gray-800">
        <div className="flex flex-col">
          <span className="text-white font-bold text-lg tracking-tight">FB Automator</span>
          <span className="text-xs text-blue-400 font-medium">Professional Suite</span>
        </div>
      </div>
      <nav className="flex-1 px-4 py-6 space-y-1.5">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
                isActive 
                  ? "bg-blue-600 text-white shadow-md shadow-blue-900/20" 
                  : "hover:bg-gray-800 hover:text-white"
              )}
            >
              <Icon className={cn("w-4 h-4", isActive ? "text-white" : "text-gray-400")} />
              {item.name}
            </Link>
          );
        })}
      </nav>
      <div className="p-4 border-t border-gray-800 bg-gray-900">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white font-semibold shadow-inner">
            AD
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-medium text-white">Admin User</span>
            <span className="text-[11px] text-gray-400 flex items-center gap-1.5 mt-0.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
              </span>
              System Online
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
