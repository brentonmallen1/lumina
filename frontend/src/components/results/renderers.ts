/**
 * Registers structured (JSON) result renderers with ResultView.
 * Import once for its side effect wherever results are shown.
 */
import { JSON_RENDERERS } from './ResultView';
import ListView from './ListView';
import MtgUpgradeView from './MtgUpgradeView';

JSON_RENDERERS.list = ListView;
JSON_RENDERERS.mtg = MtgUpgradeView;
