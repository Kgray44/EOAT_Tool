# Backend Selection Migration Strategy

`EOAT_ATLAS_DATA_BACKEND` accepts `legacy` or `mysql_api` and defaults to `legacy`. Invalid values block startup. The active backend is included in the application display name, bundle metrics, source status, and startup logging context.

- Production remains `legacy`.
- Development explicitly opts into `mysql_api`.
- `mysql_api` never falls back to Excel.
- Offline behavior is cache-only and read-only.
- No MySQL credentials are present in desktop configuration.
- The selection is an engineering migration control, not a production user preference.

Current pages consume the common `AtlasDataBundle`, so Home, search, Library lists/profiles/filters/pagination, relationship cards, Fit Check, alternatives, histories, documents/photos, Setup Packet/PDF inputs, and diagnostics receive API/cache data without a UI redesign.

