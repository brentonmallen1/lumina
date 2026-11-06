import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import { SourceCacheProvider } from './context/SourceCache';
import { JobProvider } from './context/JobContext';

// Pages load on demand so the first paint only ships the shell + home page.
const Summarize  = lazy(() => import('./pages/Summarize'));
const Transcribe = lazy(() => import('./pages/Transcribe'));
const Enhance    = lazy(() => import('./pages/Enhance'));
const Settings   = lazy(() => import('./pages/Settings'));
const Prompts    = lazy(() => import('./pages/Prompts'));
const History    = lazy(() => import('./pages/History'));
const Batch      = lazy(() => import('./pages/Batch'));
const Feeds      = lazy(() => import('./pages/Feeds'));
const Pipeline   = lazy(() => import('./pages/Pipeline'));
const Download   = lazy(() => import('./pages/Download'));
const TTS        = lazy(() => import('./pages/TTS'));
const Jobs       = lazy(() => import('./pages/Jobs'));

export default function App() {
  return (
    <JobProvider>
      <SourceCacheProvider>
        <BrowserRouter>
          <Suspense fallback={null}>
            <Routes>
              <Route element={<Layout />}>
                <Route path="/" element={<Home />} />
                <Route path="/jobs" element={<Jobs />} />
                <Route path="/summarize" element={<Summarize />} />
                <Route path="/transcribe" element={<Transcribe />} />
                <Route path="/enhance" element={<Enhance />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/prompts" element={<Prompts />} />
                <Route path="/history" element={<History />} />
                <Route path="/batch" element={<Batch />} />
                <Route path="/feeds" element={<Feeds />} />
                <Route path="/pipeline" element={<Pipeline />} />
                <Route path="/download" element={<Download />} />
                <Route path="/tts" element={<TTS />} />
                {/* Fallback */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      </SourceCacheProvider>
    </JobProvider>
  );
}
