import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";

/**
 * PageShell — Standard authenticated-page layout.
 *
 * Props:
 *   maxWidth   — Tailwind max-w class suffix, e.g. "6xl" (default) or "3xl"
 *   gradient   — Show subtle radial brand gradient (default true)
 *   withFooter — Render Footer below main content (default false)
 *   padding    — Tailwind padding on main, default "py-10"
 *   className  — Extra classes on main
 */
export function PageShell({
  children,
  maxWidth = "6xl",
  gradient = true,
  withFooter = false,
  padding = "py-10",
  className = "",
}) {
  return (
    <div className="min-h-screen bg-ayana-bg flex flex-col relative">
      {gradient && (
        <div
          className="absolute inset-0 pointer-events-none h-80"
          style={{
            background:
              "radial-gradient(1000px 320px at 100% 0%, rgba(217,108,74,0.07), transparent)," +
              "radial-gradient(800px 300px at 0% 0%, rgba(44,76,59,0.06), transparent)",
          }}
          aria-hidden="true"
        />
      )}

      <Navbar />

      <main
        className={`relative flex-1 max-w-${maxWidth} mx-auto px-5 sm:px-8 ${padding} w-full ${className}`}
      >
        {children}
      </main>

      {withFooter && <Footer />}
    </div>
  );
}
