import type { Metadata } from "next";

import { QueryProvider } from "@/components/QueryProvider";
import "@kor-travel/tokens/font.css";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Travel Concierge Admin UI",
    template: "%s · Travel Concierge Admin UI",
  },
  description: "YouTube 여행 콘텐츠를 관리하는 운영 콘솔",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko" className="font-sans">
      <body>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
