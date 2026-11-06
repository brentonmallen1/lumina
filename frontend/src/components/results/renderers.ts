/**
 * Registers structured (JSON) result renderers with ResultView.
 * Import once for its side effect wherever results are shown.
 */
import { JSON_RENDERERS } from './ResultView';

export function registerRenderer(name: string, component: (typeof JSON_RENDERERS)[string]) {
  JSON_RENDERERS[name] = component;
}
