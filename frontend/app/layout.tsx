import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";

export const metadata: Metadata = {
  title: "Intelligence Agent",
  description: "Autonomous fraud investigation agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" style={{ height: "100%" }}>
      <head>
        <link
          rel="stylesheet"
          href="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/dist/vis-network.min.css"
        />
      </head>
      <body style={{ height: "100%", overflow: "hidden" }}>
        {children}
        <Script
          src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/vis-network.min.js"
          strategy="beforeInteractive"
        />
      </body>
    </html>
  );
}
