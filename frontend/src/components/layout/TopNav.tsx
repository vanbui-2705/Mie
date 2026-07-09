import { Search, Bell, Settings, Play, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export function TopNav() {
  return (
    <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6 shrink-0 shadow-sm z-10 relative">
      <div className="flex items-center w-96 relative">
        <Search className="w-4 h-4 absolute left-3 text-gray-400" />
        <Input 
          type="text" 
          placeholder="Tìm kiếm tác vụ..." 
          className="pl-9 bg-gray-50 border-gray-200 focus-visible:ring-blue-600 h-9 rounded-md transition-all focus:bg-white"
        />
      </div>
      
      <div className="hidden md:flex items-center gap-8 text-sm font-medium text-gray-500">
        <span className="hover:text-gray-900 cursor-pointer transition-colors relative after:absolute after:bottom-[-22px] after:left-0 after:h-[2px] after:w-full hover:after:bg-blue-600">System Health</span>
        <span className="hover:text-gray-900 cursor-pointer transition-colors relative after:absolute after:bottom-[-22px] after:left-0 after:h-[2px] after:w-full hover:after:bg-blue-600">Tasks</span>
        <span className="hover:text-gray-900 cursor-pointer transition-colors relative after:absolute after:bottom-[-22px] after:left-0 after:h-[2px] after:w-full hover:after:bg-blue-600">Logs</span>
      </div>

      <div className="flex items-center gap-3">
        <Button size="sm" className="bg-blue-600 hover:bg-blue-700 text-white gap-2 shadow-sm rounded-md h-9 px-4">
          <Play className="w-4 h-4" /> Start All
        </Button>
        <Button size="sm" variant="outline" className="gap-2 bg-white text-gray-700 hover:bg-gray-50 border-gray-200 shadow-sm rounded-md h-9 px-4">
          <Square className="w-4 h-4 text-gray-500" /> Stop All
        </Button>
        <div className="w-px h-6 bg-gray-200 mx-2"></div>
        <Button variant="ghost" size="icon" className="text-gray-500 hover:text-gray-900 rounded-full">
          <Bell className="w-5 h-5" />
        </Button>
        <Button variant="ghost" size="icon" className="text-gray-500 hover:text-gray-900 rounded-full">
          <Settings className="w-5 h-5" />
        </Button>
      </div>
    </header>
  );
}
