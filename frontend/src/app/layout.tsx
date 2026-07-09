import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { DashboardShell } from "@/components/layout/DashboardShell";
import { Toaster } from "sonner";

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin", "vietnamese"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "FlowMeta — Comment Edit Delete",
  description: "Facebook automation console — precision instrument",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi">
      <body className={`${inter.variable} antialiased`}>
        <DashboardShell>{children}</DashboardShell>
        <Toaster position="bottom-right" richColors />
      </body>
    </html>
  );
}
