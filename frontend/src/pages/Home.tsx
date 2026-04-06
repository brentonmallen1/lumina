import {
  Sparkles,
  Mic,
  Youtube,
  Globe,
  FileText,
  AudioWaveform,
} from 'lucide-react';
import ToolCard from '../components/ToolCard';
import './Home.css';

export default function Home() {
  return (
    <div className="home">
      <div className="home-inner">
        {/* Hero */}
        <div className="home-hero">
          <h1 className="home-title">What would you like to do?</h1>
          <p className="home-subtitle">
            Extract, transcribe, and understand content from any source.
          </p>
        </div>

        {/* Featured: Summarize */}
        <div className="home-featured">
          <ToolCard
            icon={Sparkles}
            title="Summarize"
            description="Summarize content from any source — text, audio, video, YouTube, web pages, and PDFs — using AI."
            href="/summarize"
            featured
          />
        </div>

        {/* Tools grid */}
        <div className="home-section">
          <h2 className="home-section-title">Individual Tools</h2>
          <div className="home-grid">
            <ToolCard
              icon={Mic}
              title="Transcribe"
              description="Upload audio or video files and get accurate transcriptions using Whisper."
              href="/transcribe"
            />
            <ToolCard
              icon={Youtube}
              title="YouTube"
              description="Paste a YouTube URL — fetches captions instantly, falls back to audio transcription."
              href="/summarize"
            />
            <ToolCard
              icon={Globe}
              title="Webpage"
              description="Extract and summarize article content from any URL using Playwright."
              href="/summarize"
            />
            <ToolCard
              icon={FileText}
              title="PDF"
              description="Upload a PDF and extract its text content for summarization."
              href="/summarize"
            />
            <ToolCard
              icon={AudioWaveform}
              title="Audio Enhance"
              description="Improve audio quality before transcription — noise reduction, vocal isolation, super-resolution."
              comingSoon
            />
          </div>
        </div>
      </div>
    </div>
  );
}
