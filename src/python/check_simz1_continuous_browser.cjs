// Compatibility entry point; the reusable implementation lives in scripts/validation.
// CLI arguments are forwarded unchanged. This entry point starts browser checks only
// when explicitly executed by the user.
'use strict';
require('../scripts/validation/check_continuous_browser.cjs');
