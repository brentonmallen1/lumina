import { useState } from 'react';
import { ArrowRight, Check, Copy, ExternalLink, AlertTriangle } from 'lucide-react';
import { timestampUrl } from './timestamps';
import './results.css';

interface MtgCard {
  name: string;
  reason?: string | null;
  timestamp?: string | null;
  replaces?: string | null;
  scryfall_uri?: string | null;
  image?: string | null;
  price_usd?: number | null;
  type_line?: string | null;
  verified?: boolean;
  flags?: string[];
}

export interface MtgUpgrade {
  precon?: { name?: string | null; set_code?: string | null; matched?: boolean };
  commander?: string | null;
  budget?: string | null;
  basis?: string;
  decklist_url?: string | null;
  cards_in?: MtgCard[];
  cards_out?: MtgCard[];
  swaps?: { out: string; in: string }[];
  honorable_mentions?: { name: string; reason?: string | null }[];
  totals?: { add_cost_usd?: number; priced_cards?: number };
  import_text?: { add?: string; remove?: string };
  warnings?: string[];
}

const usd = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(2)}`);

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="summarize-action-btn"
      disabled={!text}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        } catch { /* clipboard unavailable */ }
      }}
    >
      {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      {copied ? 'Copied' : label}
    </button>
  );
}

function CardRow({ card, sourceUrl }: { card: MtgCard; sourceUrl?: string }) {
  const href = timestampUrl(sourceUrl, card.timestamp);
  return (
    <li className="mtg-card">
      {card.image
        ? <img className="mtg-card-thumb" src={card.image} alt="" loading="lazy" />
        : <span className="mtg-card-thumb mtg-card-thumb--empty" aria-hidden="true" />}
      <div className="mtg-card-body">
        <div className="mtg-card-title-row">
          {card.scryfall_uri ? (
            <a className="mtg-card-name" href={card.scryfall_uri} target="_blank" rel="noreferrer">
              {card.name}
            </a>
          ) : (
            <span className="mtg-card-name">{card.name}</span>
          )}
          <span className="mtg-card-price">{usd(card.price_usd)}</span>
        </div>
        <div className="mtg-card-meta">
          {card.type_line && <span>{card.type_line}</span>}
          {card.timestamp && (href
            ? <a className="result-ts" href={href} target="_blank" rel="noreferrer">{card.timestamp}</a>
            : <span className="result-ts">{card.timestamp}</span>)}
        </div>
        {card.reason && <p className="mtg-card-reason">{card.reason}</p>}
        {card.flags && card.flags.length > 0 && (
          <div className="mtg-card-flags">
            {card.flags.map(f => <span key={f} className="mtg-flag">{f}</span>)}
          </div>
        )}
      </div>
    </li>
  );
}

export default function MtgUpgradeView({ data, sourceUrl }: { data: MtgUpgrade; sourceUrl?: string }) {
  const adds = data.cards_in ?? [];
  const cuts = data.cards_out ?? [];
  const swaps = data.swaps ?? [];
  const mentions = data.honorable_mentions ?? [];
  const total = data.totals?.add_cost_usd;
  const priced = data.totals?.priced_cards ?? 0;

  if (adds.length === 0 && cuts.length === 0) {
    return <div className="result-empty">No card changes were found. Is this a precon upgrade guide?</div>;
  }

  return (
    <div className="result-structured mtg">
      <div className="mtg-summary">
        <div>
          <h3 className="result-structured-title">
            {data.precon?.name || 'Precon upgrade'}
            {data.precon?.set_code && <span className="mtg-set">{data.precon.set_code}</span>}
          </h3>
          <p className="result-count">
            {data.commander && <>Commander: {data.commander} · </>}
            {data.budget && <>Budget {data.budget} · </>}
            Adds cost {usd(total)}{priced < adds.length && ` (${adds.length - priced} unpriced)`}
          </p>
          <p className="result-count">
            Source: {data.basis}
            {data.decklist_url && (
              <> · <a href={data.decklist_url} target="_blank" rel="noreferrer">decklist <ExternalLink size={11} aria-hidden="true" /></a></>
            )}
            {data.precon && !data.precon.matched && ' · original precon list not found, so cuts aren’t cross-checked'}
          </p>
        </div>
      </div>

      {(data.warnings?.length ?? 0) > 0 && (
        <div className="mtg-warnings">
          {data.warnings!.map(w => (
            <p key={w}><AlertTriangle size={13} aria-hidden="true" /> {w}</p>
          ))}
        </div>
      )}

      <div className="mtg-columns">
        <section className="mtg-column" aria-label="Cards to add">
          <header className="mtg-column-head">
            <h4 className="mtg-column-title mtg-column-title--in">Add <span>{adds.length}</span></h4>
            <CopyButton text={data.import_text?.add ?? ''} label="Copy adds" />
          </header>
          <ul className="mtg-card-list">
            {adds.map(c => <CardRow key={`in-${c.name}`} card={c} sourceUrl={sourceUrl} />)}
          </ul>
        </section>
        <section className="mtg-column" aria-label="Cards to cut">
          <header className="mtg-column-head">
            <h4 className="mtg-column-title mtg-column-title--out">Cut <span>{cuts.length}</span></h4>
            <CopyButton text={data.import_text?.remove ?? ''} label="Copy cuts" />
          </header>
          <ul className="mtg-card-list">
            {cuts.map(c => <CardRow key={`out-${c.name}`} card={c} sourceUrl={sourceUrl} />)}
          </ul>
        </section>
      </div>

      {swaps.length > 0 && (
        <>
          <h4 className="result-subhead">Swaps</h4>
          <ul className="mtg-swaps">
            {swaps.map(s => (
              <li key={`${s.out}-${s.in}`}>
                <span className="mtg-swap-out">{s.out}</span>
                <ArrowRight size={13} aria-hidden="true" />
                <span className="mtg-swap-in">{s.in}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {mentions.length > 0 && (
        <>
          <h4 className="result-subhead">Also mentioned</h4>
          <p className="mtg-mentions">{mentions.map(m => m.name).join(' · ')}</p>
        </>
      )}
    </div>
  );
}
