import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

let _initialized = false;
let _counter = 0;

function initMermaid() {
  if (_initialized) return;
  _initialized = true;
  mermaid.initialize({
    startOnLoad: false,
    theme: "base",
    themeVariables: {
      fontFamily:
        'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
      fontSize: "13px",
      primaryColor: "#eef2ff",
      primaryTextColor: "#312e81",
      primaryBorderColor: "#818cf8",
      lineColor: "#6366f1",
      secondaryColor: "#f5f3ff",
      tertiaryColor: "#fdf4ff",
      noteBkgColor: "#fef3c7",
      noteTextColor: "#78350f",
      noteBorderColor: "#fbbf24",
      actorBkg: "#eef2ff",
      actorBorder: "#6366f1",
      actorTextColor: "#312e81",
      actorLineColor: "#c7d2fe",
      signalColor: "#475569",
      signalTextColor: "#475569",
      labelBoxBkgColor: "#f1f5f9",
      labelBoxBorderColor: "#94a3b8",
      labelTextColor: "#0f172a",
      loopTextColor: "#475569",
      activationBkgColor: "#c7d2fe",
      activationBorderColor: "#6366f1",
      sequenceNumberColor: "#ffffff",
    },
    sequence: {
      diagramMarginX: 20,
      diagramMarginY: 10,
      boxMargin: 10,
      boxTextMargin: 5,
      noteMargin: 10,
      messageMargin: 35,
      mirrorActors: false,
      actorMargin: 80,
    },
  });
}

interface Props {
  chart: string;
  className?: string;
}

export function Mermaid({ chart, className }: Props) {
  const [svg, setSvg] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const idRef = useRef<string>(`mmd-${++_counter}`);

  useEffect(() => {
    initMermaid();
    let cancelled = false;
    mermaid
      .render(idRef.current, chart)
      .then(({ svg }) => {
        if (!cancelled) setSvg(svg);
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (err) {
    return (
      <pre className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded p-3">
        {err}
      </pre>
    );
  }

  return (
    <div
      className={
        "overflow-x-auto [&>svg]:max-w-full [&>svg]:h-auto " + (className ?? "")
      }
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
