import './TokenSlider.css';

/** 8192 → "8K", 131072 → "128K", 1048576 → "1M". */
export function formatTokens(n: number): string {
  if (n >= 1024 * 1024 && n % (1024 * 1024) === 0) return `${n / (1024 * 1024)}M`;
  if (n >= 1024) return `${Math.round(n / 1024)}K`;
  return String(n);
}

/** Power-of-two stops from 8K up, used by every token slider. */
export const TOKEN_STOPS = [8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576];

/** Context stops for a model: standard stops up to its maximum, plus its own default/max. */
export function contextStops(max: number | null | undefined, modelDefault?: number | null): number[] {
  const limit = max ?? 262144;
  const stops = new Set(TOKEN_STOPS.filter(s => s <= limit));
  if (max) stops.add(max);
  if (modelDefault && modelDefault <= limit) stops.add(modelDefault);
  return [...stops].sort((a, b) => a - b);
}

interface TokenSliderProps {
  id: string;
  /** Stop values in ascending order; `null` is an "Off" stop (e.g. no cap). */
  stops: (number | null)[];
  value: number | null;
  onChange: (value: number | null) => void;
  /** Marks this stop as the default under its label. */
  defaultValue?: number | null;
  offLabel?: string;
  disabled?: boolean;
}

const label = (v: number | null, offLabel: string) => (v === null ? offLabel : formatTokens(v));

/**
 * A stepped slider over token counts. The thumb snaps to the given stops, so
 * users pick a sensible size instead of typing a number.
 */
export default function TokenSlider({
  id, stops, value, onChange, defaultValue, offLabel = 'Off', disabled,
}: TokenSliderProps) {
  // Nearest stop to the current value (custom values from older settings snap visually).
  const index = (() => {
    if (value === null) {
      const off = stops.indexOf(null);
      return off === -1 ? stops.length - 1 : off;
    }
    let best = 0;
    let bestDist = Infinity;
    stops.forEach((s, i) => {
      if (s === null) return;
      const d = Math.abs(Math.log2(s) - Math.log2(value));
      if (d < bestDist) { best = i; bestDist = d; }
    });
    return best;
  })();

  const last = Math.max(1, stops.length - 1);
  const readout = value === null ? offLabel : `${formatTokens(value)} tokens`;
  const isDefault = defaultValue !== undefined && value === defaultValue;

  return (
    <div className={`token-slider${disabled ? ' token-slider--disabled' : ''}`}>
      <div className="token-slider-head">
        <span className="token-slider-value">{readout}</span>
        {isDefault && <span className="token-slider-badge">default</span>}
      </div>
      <input
        id={id}
        type="range"
        className="token-slider-input"
        min={0}
        max={stops.length - 1}
        step={1}
        value={index}
        disabled={disabled || stops.length < 2}
        onChange={e => onChange(stops[Number(e.target.value)] ?? null)}
        aria-valuetext={readout}
      />
      <div className="token-slider-ticks" aria-hidden="true">
        {stops.map((s, i) => (
          <button
            key={`${s}-${i}`}
            type="button"
            tabIndex={-1}
            className={[
              'token-slider-tick',
              i === index ? 'active' : '',
              s === defaultValue ? 'is-default' : '',
            ].filter(Boolean).join(' ')}
            style={{ left: `calc(var(--thumb) / 2 + (100% - var(--thumb)) * ${i / last})` }}
            onClick={() => !disabled && onChange(s)}
          >
            {label(s, offLabel)}
          </button>
        ))}
      </div>
    </div>
  );
}
