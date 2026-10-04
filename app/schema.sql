PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS visitors (
 visitor_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, landing_book_order TEXT NOT NULL,
 is_test INTEGER NOT NULL DEFAULT 0 CHECK(is_test IN (0,1)), exclusion_reason TEXT,
 csrf_token TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS books (book_id TEXT PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seed_invites (
 token_hash TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT
);
CREATE TABLE IF NOT EXISTS seed_participants (
 visitor_id TEXT PRIMARY KEY REFERENCES visitors, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS book_contents (
 content_version_id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books,
 content_json TEXT NOT NULL, effective_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emoji_reactions (
 reaction_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors, book_id TEXT NOT NULL REFERENCES books,
 option_id TEXT, content_version_id TEXT NOT NULL REFERENCES book_contents,
 first_selected_at TEXT NOT NULL, updated_at TEXT NOT NULL, cancelled_at TEXT,
 UNIQUE(visitor_id,book_id)
);
CREATE TABLE IF NOT EXISTS poll_votes (
 vote_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors, book_id TEXT NOT NULL REFERENCES books,
 option_id TEXT, content_version_id TEXT NOT NULL REFERENCES book_contents,
 first_voted_at TEXT NOT NULL, updated_at TEXT NOT NULL, cancelled_at TEXT,
 UNIQUE(visitor_id,book_id)
);
CREATE TABLE IF NOT EXISTS reviews (
 review_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors, book_id TEXT NOT NULL REFERENCES books,
 review_type TEXT NOT NULL CHECK(review_type IN ('short','full')), body TEXT NOT NULL,
 content_version_id TEXT NOT NULL REFERENCES book_contents, first_submitted_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, deleted_at TEXT, body_purged_at TEXT,
 UNIQUE(visitor_id,book_id,review_type)
);
CREATE TABLE IF NOT EXISTS likes (
 like_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors, review_id TEXT NOT NULL REFERENCES reviews,
 first_liked_at TEXT NOT NULL, updated_at TEXT NOT NULL, cancelled_at TEXT,
 UNIQUE(visitor_id,review_id)
);
CREATE TABLE IF NOT EXISTS replies (
 reply_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors, review_id TEXT NOT NULL REFERENCES reviews,
 body TEXT NOT NULL, first_submitted_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT, body_purged_at TEXT
);
CREATE TABLE IF NOT EXISTS page_views (
 page_view_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors, book_id TEXT REFERENCES books,
 content_version_id TEXT REFERENCES book_contents, displayed_book_order TEXT,
 source_book_select_event_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors, event_type TEXT NOT NULL,
 timestamp TEXT NOT NULL, page_view_id TEXT NOT NULL REFERENCES page_views, book_id TEXT REFERENCES books,
 content_version_id TEXT REFERENCES book_contents, landing_page_view_id TEXT, display_position INTEGER,
 displayed_book_order TEXT, source_book_select_event_id TEXT, target_type TEXT, target_id TEXT,
 option_id TEXT, previous_option_id TEXT, action TEXT, reveal_source TEXT, exposure_area TEXT,
 cause_event_id TEXT, exposure_context TEXT NOT NULL, client_occurred_at TEXT NOT NULL,
 client_sequence INTEGER NOT NULL, body_length INTEGER, short_submitted_before INTEGER,
 UNIQUE(page_view_id, client_sequence)
);
CREATE TABLE IF NOT EXISTS requests (
 event_id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors, fingerprint TEXT NOT NULL,
 response_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_lookup ON events(visitor_id,book_id,event_type,timestamp);
CREATE INDEX IF NOT EXISTS events_period ON events(timestamp,book_id,event_type);
CREATE INDEX IF NOT EXISTS reviews_book ON reviews(book_id,review_type,first_submitted_at);
CREATE INDEX IF NOT EXISTS replies_review ON replies(review_id,first_submitted_at);
