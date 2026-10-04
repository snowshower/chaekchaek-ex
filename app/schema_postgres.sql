CREATE TABLE IF NOT EXISTS visitors (
 visitor_id TEXT COLLATE "C" PRIMARY KEY, created_at TEXT COLLATE "C" NOT NULL, landing_book_order TEXT COLLATE "C" NOT NULL,
 is_test INTEGER NOT NULL DEFAULT 0 CHECK(is_test IN (0,1)), exclusion_reason TEXT COLLATE "C",
 csrf_token TEXT COLLATE "C" NOT NULL
);
CREATE TABLE IF NOT EXISTS books (book_id TEXT COLLATE "C" PRIMARY KEY, title TEXT COLLATE "C" NOT NULL);
CREATE TABLE IF NOT EXISTS seed_invites (
 token_hash TEXT COLLATE "C" PRIMARY KEY, created_at TEXT COLLATE "C" NOT NULL,
 expires_at TEXT COLLATE "C" NOT NULL, used_at TEXT COLLATE "C"
);
CREATE TABLE IF NOT EXISTS seed_participants (
 visitor_id TEXT COLLATE "C" PRIMARY KEY REFERENCES visitors, created_at TEXT COLLATE "C" NOT NULL
);
CREATE TABLE IF NOT EXISTS book_contents (
 content_version_id TEXT COLLATE "C" PRIMARY KEY, book_id TEXT COLLATE "C" NOT NULL REFERENCES books,
 content_json TEXT COLLATE "C" NOT NULL, effective_at TEXT COLLATE "C" NOT NULL
);
CREATE TABLE IF NOT EXISTS emoji_reactions (
 reaction_id TEXT COLLATE "C" PRIMARY KEY, visitor_id TEXT COLLATE "C" NOT NULL REFERENCES visitors, book_id TEXT COLLATE "C" NOT NULL REFERENCES books,
 option_id TEXT COLLATE "C", content_version_id TEXT COLLATE "C" NOT NULL REFERENCES book_contents,
 first_selected_at TEXT COLLATE "C" NOT NULL, updated_at TEXT COLLATE "C" NOT NULL, cancelled_at TEXT COLLATE "C",
 UNIQUE(visitor_id,book_id)
);
CREATE TABLE IF NOT EXISTS poll_votes (
 vote_id TEXT COLLATE "C" PRIMARY KEY, visitor_id TEXT COLLATE "C" NOT NULL REFERENCES visitors, book_id TEXT COLLATE "C" NOT NULL REFERENCES books,
 option_id TEXT COLLATE "C", content_version_id TEXT COLLATE "C" NOT NULL REFERENCES book_contents,
 first_voted_at TEXT COLLATE "C" NOT NULL, updated_at TEXT COLLATE "C" NOT NULL, cancelled_at TEXT COLLATE "C",
 UNIQUE(visitor_id,book_id)
);
CREATE TABLE IF NOT EXISTS reviews (
 review_id TEXT COLLATE "C" PRIMARY KEY, visitor_id TEXT COLLATE "C" NOT NULL REFERENCES visitors, book_id TEXT COLLATE "C" NOT NULL REFERENCES books,
 review_type TEXT COLLATE "C" NOT NULL CHECK(review_type IN ('short','full')), body TEXT COLLATE "C" NOT NULL,
 content_version_id TEXT COLLATE "C" NOT NULL REFERENCES book_contents, first_submitted_at TEXT COLLATE "C" NOT NULL,
 updated_at TEXT COLLATE "C" NOT NULL, deleted_at TEXT COLLATE "C", body_purged_at TEXT COLLATE "C",
 UNIQUE(visitor_id,book_id,review_type)
);
CREATE TABLE IF NOT EXISTS likes (
 like_id TEXT COLLATE "C" PRIMARY KEY, visitor_id TEXT COLLATE "C" NOT NULL REFERENCES visitors, review_id TEXT COLLATE "C" NOT NULL REFERENCES reviews,
 first_liked_at TEXT COLLATE "C" NOT NULL, updated_at TEXT COLLATE "C" NOT NULL, cancelled_at TEXT COLLATE "C",
 UNIQUE(visitor_id,review_id)
);
CREATE TABLE IF NOT EXISTS replies (
 reply_id TEXT COLLATE "C" PRIMARY KEY, visitor_id TEXT COLLATE "C" NOT NULL REFERENCES visitors, review_id TEXT COLLATE "C" NOT NULL REFERENCES reviews,
 body TEXT COLLATE "C" NOT NULL, first_submitted_at TEXT COLLATE "C" NOT NULL, updated_at TEXT COLLATE "C" NOT NULL, deleted_at TEXT COLLATE "C", body_purged_at TEXT COLLATE "C"
);
CREATE TABLE IF NOT EXISTS page_views (
 page_view_id TEXT COLLATE "C" PRIMARY KEY, visitor_id TEXT COLLATE "C" NOT NULL REFERENCES visitors, book_id TEXT COLLATE "C" REFERENCES books,
 content_version_id TEXT COLLATE "C" REFERENCES book_contents, displayed_book_order TEXT COLLATE "C",
 source_book_select_event_id TEXT COLLATE "C", created_at TEXT COLLATE "C" NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT COLLATE "C" PRIMARY KEY, visitor_id TEXT COLLATE "C" NOT NULL REFERENCES visitors, event_type TEXT COLLATE "C" NOT NULL,
 timestamp TEXT COLLATE "C" NOT NULL, page_view_id TEXT COLLATE "C" NOT NULL REFERENCES page_views, book_id TEXT COLLATE "C" REFERENCES books,
 content_version_id TEXT COLLATE "C" REFERENCES book_contents, landing_page_view_id TEXT COLLATE "C", display_position INTEGER,
 displayed_book_order TEXT COLLATE "C", source_book_select_event_id TEXT COLLATE "C", target_type TEXT COLLATE "C", target_id TEXT COLLATE "C",
 option_id TEXT COLLATE "C", previous_option_id TEXT COLLATE "C", action TEXT COLLATE "C", reveal_source TEXT COLLATE "C", exposure_area TEXT COLLATE "C",
 cause_event_id TEXT COLLATE "C", exposure_context TEXT COLLATE "C" NOT NULL, client_occurred_at TEXT COLLATE "C" NOT NULL,
 client_sequence INTEGER NOT NULL, body_length INTEGER, short_submitted_before INTEGER,
 UNIQUE(page_view_id, client_sequence)
);
CREATE TABLE IF NOT EXISTS requests (
 event_id TEXT COLLATE "C" PRIMARY KEY, visitor_id TEXT COLLATE "C" NOT NULL REFERENCES visitors, fingerprint TEXT COLLATE "C" NOT NULL,
 response_json TEXT COLLATE "C" NOT NULL
);
CREATE INDEX IF NOT EXISTS events_lookup ON events(visitor_id,book_id,event_type,timestamp);
CREATE INDEX IF NOT EXISTS events_period ON events(timestamp,book_id,event_type);
CREATE INDEX IF NOT EXISTS reviews_book ON reviews(book_id,review_type,first_submitted_at);
CREATE INDEX IF NOT EXISTS replies_review ON replies(review_id,first_submitted_at);
