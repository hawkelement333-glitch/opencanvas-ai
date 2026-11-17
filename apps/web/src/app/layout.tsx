import type { Metadata } from "next";
import type { ReactNode } from "react";

import { validatedPublicApiUrl } from "@/lib/runtime-api";

import { AppProviders } from "@/components/app-providers";

import "@xyflow/react/dist/style.css";
import "./globals.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "SolarPlexus Mobius",
  description: "A visual, source-grounded workspace for auditable AI knowledge work",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const configured = process.env.OPENCANVAS_PUBLIC_API_URL;
  const apiBaseUrl = configured ? validatedPublicApiUrl(configured) : undefined;
  return (
    <html lang="en" data-api-base-url={apiBaseUrl}>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
