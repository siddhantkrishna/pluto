import type { Metadata } from "next";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter-tight/500.css";
import "@fontsource/inter-tight/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./globals.css";
export const metadata: Metadata = {
  title: "PLUTO · VOGON",
  description: "Institutional data intelligence infrastructure",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
