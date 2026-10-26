// Our tools, in page order and in the header's groups. The header, the drawer menu, the page's
// sections and the phone's "Explore more" cards are all drawn from this one list. `id` is also the
// section's element id, so links such as /#market-value keep working.
export const TOOL_GROUPS = [
  {
    title: 'Land records',
    tools: [
      { id: 'market-value', label: 'Market Value', icon: 'ti-currency-rupee', sheet: 'Land Market Value', desc: 'Government land rates by village or locality' },
      { id: 'pattadar-passbook', label: 'Land Details', icon: 'ti-id-badge-2', sheet: 'Land Details Search', desc: 'Land status and owner from Bhu Bharati' },
      { id: 'adangal', label: 'Adangal', icon: 'ti-notebook', sheet: 'Adangal (Pahani)', desc: 'Pahani record by survey number' },
      { id: 'prohibited-lands', label: 'Prohibited Lands', icon: 'ti-ban', sheet: 'Prohibited Lands (22A)', desc: 'Section 22-A lists and orders' },
    ],
  },
  {
    title: 'Maps',
    tools: [
      { id: 'survey-map', label: 'Survey Map', icon: 'ti-map-search', sheet: 'Survey Map', desc: 'A survey number on a satellite map' },
      { id: 'village-map', label: 'Village Map', icon: 'ti-map-2', sheet: 'Village Map', desc: 'A whole village’s survey map' },
      { id: 'hydra-ftl-map', label: 'Hydra FTL Map', icon: 'ti-ripple', sheet: 'Hydra FTL Map', desc: 'Lake FTL and buffer zone maps' },
    ],
  },
  {
    title: 'Municipal & approvals',
    tools: [
      { id: 'ghmc-mutation', label: 'GHMC Mutation', icon: 'ti-home-2', sheet: 'GHMC Mutation Status', desc: 'Hyderabad mutation status' },
      { id: 'ghmc-property-tax', label: 'GHMC Property Tax', icon: 'ti-receipt', sheet: 'GHMC Property Tax', desc: 'Hyderabad property tax by PTIN' },
      { id: 'cdma-tax-receipt', label: 'CDMA Tax Receipt', icon: 'ti-receipt-2', sheet: 'Property Tax Receipt (CDMA)', desc: 'Tax receipts for towns outside Hyderabad' },
      { id: 'building-permission', label: 'Building Permission', icon: 'ti-building', sheet: 'Building Permission (TG‑bPASS)', desc: 'TG-bPASS permission letters' },
      { id: 'rera-certificate', label: 'RERA Certificate', icon: 'ti-certificate', sheet: 'RERA Certificate', desc: 'Project registration certificates' },
    ],
  },
]

export const TOOLS = TOOL_GROUPS.flatMap((g) => g.tools)

// Shown on the phone's page itself (the others open from "Explore more"), and first on desktop.
export const MAIN_TOOL = 'market-value'
