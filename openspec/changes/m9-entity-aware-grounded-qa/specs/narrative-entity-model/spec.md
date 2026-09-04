## ADDED Requirements

### Requirement: Narrative identity and playable form separation
The system MUST represent a narrative person separately from each independently selectable playable form while retaining evidence-backed links between them.

#### Scenario: One person has two playable forms
- **WHEN** official data registers both `姬子` and `姬子·启行` as playable characters belonging to the same narrative person
- **THEN** the system stores two playable-form identities linked to one narrative-person identity rather than flattening the form name into an ordinary alias

### Requirement: Typed names and labels
Every canonical name, official alias, punctuation variant, and player-facing shorthand MUST retain a type and MUST NOT be presented as official wording unless supported by official evidence.

#### Scenario: Player shorthand is displayed
- **WHEN** the interface uses `SP` to help a player understand an alternate playable form
- **THEN** it labels that wording as player terminology and does not cite it as an official claim

### Requirement: Evidence-backed identity links
A playable-form or same-person link MUST cite current official evidence or remain pending and hidden from factual answers.

#### Scenario: Two similarly named characters lack identity evidence
- **WHEN** names are similar but current official evidence does not establish that they are the same narrative person
- **THEN** the system reports ambiguity and does not create a visible same-person relation

### Requirement: Stable entity migration
Entity migration MUST preserve stable evidence links and approved unrelated relations while splitting an existing flattened entity into a narrative person and playable forms.

#### Scenario: Flattened character aliases are migrated
- **WHEN** the existing `姬子` entity containing `姬子·启行` as an alias is migrated
- **THEN** citations and unrelated approved relations remain resolvable and the two playable forms receive stable distinct identities
