import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { DataProvider } from "@/components/DataProvider";
import { Sidebar } from "@/components/Sidebar";
import { StatusBanners } from "@/components/StatusBanners";

export const metadata: Metadata = {
  title: "DevPilot",
  description: "Local-first repository intelligence",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-zinc-950 text-zinc-200 antialiased">
        <DataProvider>
          <div className="flex min-h-screen flex-col md:flex-row">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <StatusBanners />
              <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-6">{children}</main>
            </div>
          </div>
        </DataProvider>
      </body>
    </html>
  );
}
