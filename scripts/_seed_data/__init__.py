"""Question banks per subject. Each module exposes:

    TOPICS: list[dict]            # name_en, name_uz, name_ru, weight
    STUDY_CLOSED: list[tuple]     # (topic_en, body_en, options_dict, correct, difficulty)
    STUDY_OPEN:   list[tuple]     # (topic_en, body_en, accepted_list, difficulty)
    BATTLE:       list[tuple]     # (topic_en, body_en, options_dict, correct, difficulty)

Counts target ≥45 study questions and ≥50 battle questions per subject.
"""
