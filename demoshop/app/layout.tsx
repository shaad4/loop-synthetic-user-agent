import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DemoShop",
  description: "A deliberately imperfect storefront for Loop.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
