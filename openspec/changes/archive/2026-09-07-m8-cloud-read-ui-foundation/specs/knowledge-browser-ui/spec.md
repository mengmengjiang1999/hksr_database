## ADDED Requirements

### Requirement: Navigable knowledge workspace
The web interface MUST provide distinct question answering, evidence search, coverage, and source-detail views without a full page reload.

#### Scenario: User changes workspace view
- **WHEN** the user selects a primary navigation item or opens a source result
- **THEN** the corresponding view is shown and browser back navigation can restore the previous view

### Requirement: Filterable evidence search
The web interface SHALL allow a user to search evidence and restrict results by available source type, context, and version metadata.

#### Scenario: User applies search filters
- **WHEN** a non-empty query is submitted with one or more filters
- **THEN** the interface sends those filters to the search API and renders matching evidence cards with score, source metadata, excerpt, and source-detail access

### Requirement: Traceable source details
The web interface MUST show source identity, processing metadata, document sections, and the original official page link for a selected source.

#### Scenario: User opens a source result
- **WHEN** the source-detail API resolves the selected source
- **THEN** the interface renders its metadata and document inventory and offers a safe link to the original page

### Requirement: Collection-aware coverage
The web interface SHALL show a read-only snapshot of source processing counts and searchable catalog facets without presenting incomplete collection as a service failure.

#### Scenario: Collection is still running
- **WHEN** discovered or fetched source counts exceed parsed source counts
- **THEN** the coverage view labels the corpus as growing and still displays all current counts

### Requirement: Complete interaction states
Every network-backed view MUST provide explicit loading, empty, insufficient-evidence, and failure states appropriate to the operation.

#### Scenario: Search has no matches
- **WHEN** a valid search request returns an empty result list
- **THEN** the interface explains that no current evidence matched and suggests changing the query or filters

### Requirement: Responsive and accessible presentation
The interface MUST remain usable on narrow screens and SHALL use semantic controls, keyboard focus indicators, and live status messaging for asynchronous operations.

#### Scenario: User operates on a mobile-width viewport
- **WHEN** the viewport is 640 CSS pixels wide or narrower
- **THEN** navigation, forms, result cards, and source details remain readable without horizontal page scrolling
