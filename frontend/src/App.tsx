import { useCallback, useEffect, useState } from "react";
import FloatingMenu, { type MenuItem } from "@/components/ui/liquid-morph-floating-menu";
import { CinematicFooter } from "@/components/ui/motion-footer";
import { Hero } from "@/components/sections/Hero";
import { TheAnswer } from "@/components/sections/TheAnswer";
import { WhyAGraph } from "@/components/sections/WhyAGraph";
import { Capabilities } from "@/components/sections/Capabilities";
import { HowItWorks } from "@/components/sections/HowItWorks";
import { Console } from "@/components/sections/Console";

const REPO_URL = "https://github.com/Jhaycrypt001/adit";

type View = "home" | "console";

/**
 * Two views, no router.
 *
 * A router would buy deep links to exactly one extra screen, at the cost of a
 * dependency and a build step this doesn't otherwise need. The hash is kept in
 * sync by hand instead, so `#console` still survives a reload and the back
 * button still works -- which is the part of routing that actually matters here.
 */
export default function App() {
  const [view, setView] = useState<View>(
    () => (window.location.hash === "#console" ? "console" : "home"),
  );

  useEffect(() => {
    const sync = () => setView(window.location.hash === "#console" ? "console" : "home");
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const go = useCallback((next: View) => {
    // Writing the hash fires `hashchange`, which sets the state -- one path in,
    // so the two can't disagree.
    window.location.hash = next === "console" ? "#console" : "";
    if (next === "console") window.scrollTo({ top: 0 });
    setView(next);
  }, []);

  const openConsole = useCallback(() => go("console"), [go]);

  const menuItems: MenuItem[] = [
    {
      label: "Home",
      onClick: () => {
        go("home");
        window.scrollTo({ top: 0, behavior: "smooth" });
      },
    },
    { label: "Console", onClick: openConsole },
    { label: "Source", onClick: () => window.open(REPO_URL, "_blank", "noreferrer") },
  ];

  return (
    <div className="relative w-full overflow-x-hidden bg-background">
      {view === "console" ? (
        <Console onBack={() => go("home")} />
      ) : (
        <>
          {/* z-10 and an opaque background: the footer below is position:fixed,
              and without a stacking context above it the page content would
              scroll straight over the top of the curtain reveal. */}
          <main className="relative z-10 w-full bg-background">
            <Hero onOpenConsole={openConsole} />
            <TheAnswer />
            <WhyAGraph />
            <Capabilities />
            <HowItWorks />
          </main>
          <CinematicFooter />
        </>
      )}

      <FloatingMenu items={menuItems} />
    </div>
  );
}
