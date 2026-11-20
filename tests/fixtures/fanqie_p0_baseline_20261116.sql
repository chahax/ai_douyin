-- Baseline P0 schema from a read-only production schema snapshot, no rows or credentials.

CREATE TABLE "fanqie_batch_books" (
	id INTEGER NOT NULL, 
	book_name VARCHAR(255) NOT NULL, 
	status VARCHAR(32), 
	chapters INTEGER, 
	interval_s INTEGER, 
	book_id VARCHAR(64), 
	chapters_fetched INTEGER, 
	total_chapters_seen INTEGER, 
	paywall_hit BOOLEAN, 
	material_path VARCHAR(512), 
	error_message TEXT, 
	duration_ms INTEGER, 
	added_at DATETIME, 
	last_fetched_at DATETIME, 
	attempt_count INTEGER, 
	note TEXT, 
	fanqie_book_pk INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT fk_fanqie_batch_books_book_pk FOREIGN KEY(fanqie_book_pk) REFERENCES fanqie_books (id)
);

CREATE TABLE fanqie_bindings (
	id INTEGER NOT NULL, 
	binding_uuid VARCHAR(64) NOT NULL, 
	task_id INTEGER NOT NULL, 
	publish_id INTEGER NOT NULL, 
	status VARCHAR(32), 
	attempt_count INTEGER, 
	submitted_url VARCHAR(512), 
	response_snapshot_path VARCHAR(512), 
	screenshot_path VARCHAR(512), 
	bound_at DATETIME, 
	last_attempt_at DATETIME, 
	operator VARCHAR(64), 
	last_error TEXT, 
	created_at DATETIME, idempotency_key VARCHAR(128), before_screenshot_path VARCHAR(512), after_screenshot_path VARCHAR(512), captcha_detected BOOLEAN DEFAULT '0' NOT NULL, manual_gate_detected BOOLEAN DEFAULT '0' NOT NULL, field_contract_json JSON, 
	PRIMARY KEY (id), 
	UNIQUE (binding_uuid), 
	FOREIGN KEY(task_id) REFERENCES fanqie_promotion_tasks (id), 
	FOREIGN KEY(publish_id) REFERENCES fanqie_publish_records (id)
);

CREATE TABLE fanqie_books (
	id INTEGER NOT NULL, 
	book_uuid VARCHAR(64) NOT NULL, 
	fanqie_book_id VARCHAR(64), 
	book_name VARCHAR(255) DEFAULT '' NOT NULL, 
	author VARCHAR(255) DEFAULT '' NOT NULL, 
	abstract TEXT, 
	categories_json JSON, 
	tags_json JSON, 
	serial_status VARCHAR(32), 
	word_count INTEGER, 
	source_ranking VARCHAR(128), 
	selection_filters_json JSON, 
	selection_reason TEXT, 
	selected_by VARCHAR(64), 
	material_status VARCHAR(32), 
	material_root VARCHAR(512), 
	material_hash VARCHAR(128), 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (book_uuid), 
	UNIQUE (fanqie_book_id)
);

CREATE TABLE fanqie_chapters (
	id INTEGER NOT NULL, 
	book_id INTEGER NOT NULL, 
	chapter_index INTEGER NOT NULL, 
	chapter_title VARCHAR(255), 
	source_url VARCHAR(512), 
	content_path VARCHAR(512), 
	content_hash VARCHAR(128), 
	char_count INTEGER, 
	is_paywalled BOOLEAN, 
	fetched_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(book_id) REFERENCES fanqie_books (id)
);

CREATE TABLE fanqie_douyin_accounts (
	id INTEGER NOT NULL, 
	account_uuid VARCHAR(64) NOT NULL, 
	account_key VARCHAR(128) NOT NULL, 
	display_name VARCHAR(255), 
	masked_login_name VARCHAR(64), 
	status VARCHAR(32), 
	profile_dir VARCHAR(512), 
	platform_uid VARCHAR(128), 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (account_uuid), 
	UNIQUE (account_key)
);

CREATE TABLE fanqie_operation_events (
	id INTEGER NOT NULL, 
	event_uuid VARCHAR(64) NOT NULL, 
	task_id INTEGER, 
	event_type VARCHAR(32) NOT NULL, 
	from_status VARCHAR(32), 
	to_status VARCHAR(32), 
	actor_type VARCHAR(32), 
	actor_id VARCHAR(64), 
	payload_json JSON, 
	artifact_path VARCHAR(512), 
	created_at DATETIME, audit_artifact_hash VARCHAR(128), 
	PRIMARY KEY (id), 
	UNIQUE (event_uuid), 
	FOREIGN KEY(task_id) REFERENCES fanqie_promotion_tasks (id)
);

CREATE TABLE fanqie_performance_daily (
	id INTEGER NOT NULL, 
	publish_id INTEGER NOT NULL, 
	snapshot_date VARCHAR(10) NOT NULL, 
	views INTEGER, 
	likes INTEGER, 
	comments INTEGER, 
	shares INTEGER, 
	completion_rate FLOAT, 
	fanqie_clicks INTEGER, 
	conversions INTEGER, 
	revenue FLOAT, 
	raw_snapshot_path VARCHAR(512), 
	collected_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(publish_id) REFERENCES fanqie_publish_records (id)
);

CREATE TABLE fanqie_promotion_task_aliases (
	id INTEGER NOT NULL, 
	task_id INTEGER NOT NULL, 
	alias VARCHAR(255) NOT NULL, 
	is_current BOOLEAN, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES fanqie_promotion_tasks (id)
);

CREATE TABLE fanqie_promotion_tasks (
	id INTEGER NOT NULL, 
	task_uuid VARCHAR(64) NOT NULL, 
	book_id INTEGER, 
	platform_task_id VARCHAR(128), 
	promotion_alias VARCHAR(255), 
	publish_type VARCHAR(64), 
	status VARCHAR(32), 
	failure_stage VARCHAR(32), 
	version INTEGER DEFAULT '1' NOT NULL, 
	valid_from DATETIME, 
	valid_until DATETIME, 
	application_snapshot_path VARCHAR(512), 
	last_error TEXT, 
	manual_reason TEXT, 
	created_by VARCHAR(64), 
	created_at DATETIME, 
	updated_at DATETIME, idempotency_key VARCHAR(128), next_poll_at DATETIME, publish_attempt_count INTEGER DEFAULT '0' NOT NULL, bind_attempt_count INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (task_uuid), 
	FOREIGN KEY(book_id) REFERENCES fanqie_books (id)
);

CREATE TABLE fanqie_publish_records (
	id INTEGER NOT NULL, 
	publish_uuid VARCHAR(64) NOT NULL, 
	task_id INTEGER NOT NULL, 
	video_job_id INTEGER, 
	douyin_account_id INTEGER, 
	status VARCHAR(32), 
	title_snapshot VARCHAR(255), 
	description_snapshot TEXT, 
	hashtags_json JSON, 
	douyin_video_id VARCHAR(128), 
	douyin_video_url VARCHAR(512), 
	published_at DATETIME, 
	synced_at DATETIME, 
	platform_response_path VARCHAR(512), 
	last_error TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, idempotency_key VARCHAR(128), preflight_snapshot_path VARCHAR(512), browser_upload_evidence_path VARCHAR(512), review_check_count INTEGER DEFAULT '0' NOT NULL, last_poll_at DATETIME, next_poll_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (publish_uuid), 
	UNIQUE (douyin_video_id), 
	UNIQUE (douyin_video_url), 
	FOREIGN KEY(task_id) REFERENCES fanqie_promotion_tasks (id), 
	FOREIGN KEY(video_job_id) REFERENCES fanqie_video_jobs (id), 
	FOREIGN KEY(douyin_account_id) REFERENCES fanqie_douyin_accounts (id)
);

CREATE TABLE fanqie_reviews (
	id INTEGER NOT NULL, 
	review_uuid VARCHAR(64) NOT NULL, 
	video_job_id INTEGER NOT NULL, 
	decision VARCHAR(32) NOT NULL, 
	reviewer VARCHAR(64), 
	reviewed_at DATETIME, 
	issues_json JSON, 
	comment TEXT, 
	machine_gate_passed BOOLEAN, 
	override_reason TEXT, 
	approved_sha256 VARCHAR(128), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (review_uuid), 
	FOREIGN KEY(video_job_id) REFERENCES fanqie_video_jobs (id)
);

CREATE TABLE fanqie_script_versions (
	id INTEGER NOT NULL, 
	script_uuid VARCHAR(64) NOT NULL, 
	task_id INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	parent_script_id INTEGER, 
	chapter_range VARCHAR(128), 
	hook TEXT, 
	script_text TEXT, 
	title VARCHAR(255), 
	description TEXT, 
	hashtags_json JSON, 
	cta VARCHAR(255), 
	spoiler_level VARCHAR(32), 
	model_name VARCHAR(128), 
	prompt_version VARCHAR(64), 
	generation_params_json JSON, 
	status VARCHAR(32), 
	content_hash VARCHAR(128), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (script_uuid), 
	FOREIGN KEY(task_id) REFERENCES fanqie_promotion_tasks (id)
);

CREATE TABLE fanqie_video_jobs (
	id INTEGER NOT NULL, 
	job_uuid VARCHAR(64) NOT NULL, 
	task_id INTEGER NOT NULL, 
	script_id INTEGER NOT NULL, 
	video_mode VARCHAR(64), 
	quality_profile VARCHAR(32), 
	status VARCHAR(32), 
	failure_stage VARCHAR(32), 
	error_message TEXT, 
	request_path VARCHAR(512), 
	manifest_path VARCHAR(512), 
	output_path VARCHAR(512), 
	quality_report_path VARCHAR(512), 
	review_packet_path VARCHAR(512), 
	output_sha256 VARCHAR(128), 
	runtime_json JSON, 
	duration_ms INTEGER, 
	cost_json JSON, 
	started_at DATETIME, 
	finished_at DATETIME, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (job_uuid), 
	FOREIGN KEY(task_id) REFERENCES fanqie_promotion_tasks (id), 
	FOREIGN KEY(script_id) REFERENCES fanqie_script_versions (id)
);

CREATE INDEX ix_fanqie_batch_books_book_name ON fanqie_batch_books (book_name);

CREATE INDEX ix_fanqie_batch_books_book_pk ON fanqie_batch_books (fanqie_book_pk);

CREATE INDEX ix_fanqie_batch_books_id ON fanqie_batch_books (id);

CREATE INDEX ix_fanqie_batch_books_status ON fanqie_batch_books (status);

CREATE INDEX ix_fanqie_bindings_binding_uuid ON fanqie_bindings (binding_uuid);

CREATE INDEX ix_fanqie_bindings_id ON fanqie_bindings (id);

CREATE UNIQUE INDEX ix_fanqie_bindings_idempotency_key_unique ON fanqie_bindings (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE INDEX ix_fanqie_bindings_publish_id ON fanqie_bindings (publish_id);

CREATE INDEX ix_fanqie_bindings_status ON fanqie_bindings (status);

CREATE INDEX ix_fanqie_bindings_task_id ON fanqie_bindings (task_id);

CREATE INDEX ix_fanqie_books_book_uuid ON fanqie_books (book_uuid);

CREATE INDEX ix_fanqie_books_fanqie_book_id ON fanqie_books (fanqie_book_id);

CREATE INDEX ix_fanqie_books_id ON fanqie_books (id);

CREATE INDEX ix_fanqie_chapters_book_id ON fanqie_chapters (book_id);

CREATE INDEX ix_fanqie_chapters_id ON fanqie_chapters (id);

CREATE INDEX ix_fanqie_douyin_accounts_account_key ON fanqie_douyin_accounts (account_key);

CREATE INDEX ix_fanqie_douyin_accounts_id ON fanqie_douyin_accounts (id);

CREATE INDEX ix_fanqie_operation_events_created_at ON fanqie_operation_events (created_at);

CREATE INDEX ix_fanqie_operation_events_event_type ON fanqie_operation_events (event_type);

CREATE INDEX ix_fanqie_operation_events_id ON fanqie_operation_events (id);

CREATE INDEX ix_fanqie_operation_events_task ON fanqie_operation_events (task_id);

CREATE INDEX ix_fanqie_performance_daily_id ON fanqie_performance_daily (id);

CREATE INDEX ix_fanqie_performance_daily_publish_id ON fanqie_performance_daily (publish_id);

CREATE INDEX ix_fanqie_promotion_task_aliases_id ON fanqie_promotion_task_aliases (id);

CREATE INDEX ix_fanqie_promotion_tasks_book_id ON fanqie_promotion_tasks (book_id);

CREATE INDEX ix_fanqie_promotion_tasks_id ON fanqie_promotion_tasks (id);

CREATE INDEX ix_fanqie_promotion_tasks_idempotency_key ON fanqie_promotion_tasks (idempotency_key);

CREATE INDEX ix_fanqie_promotion_tasks_next_poll_at ON fanqie_promotion_tasks (next_poll_at);

CREATE INDEX ix_fanqie_promotion_tasks_status ON fanqie_promotion_tasks (status);

CREATE INDEX ix_fanqie_promotion_tasks_task_uuid ON fanqie_promotion_tasks (task_uuid);

CREATE INDEX ix_fanqie_publish_records_douyin_account_id ON fanqie_publish_records (douyin_account_id);

CREATE INDEX ix_fanqie_publish_records_douyin_video_id ON fanqie_publish_records (douyin_video_id);

CREATE INDEX ix_fanqie_publish_records_id ON fanqie_publish_records (id);

CREATE INDEX ix_fanqie_publish_records_publish_uuid ON fanqie_publish_records (publish_uuid);

CREATE INDEX ix_fanqie_publish_records_status ON fanqie_publish_records (status);

CREATE INDEX ix_fanqie_publish_records_task_id ON fanqie_publish_records (task_id);

CREATE INDEX ix_fanqie_publish_records_video_job_id ON fanqie_publish_records (video_job_id);

CREATE UNIQUE INDEX ix_fanqie_publish_recs_idempotency_key ON fanqie_publish_records (idempotency_key);

CREATE INDEX ix_fanqie_publish_recs_next_poll_at ON fanqie_publish_records (next_poll_at);

CREATE INDEX ix_fanqie_reviews_id ON fanqie_reviews (id);

CREATE INDEX ix_fanqie_reviews_video_job_id ON fanqie_reviews (video_job_id);

CREATE INDEX ix_fanqie_script_versions_id ON fanqie_script_versions (id);

CREATE INDEX ix_fanqie_script_versions_task_id ON fanqie_script_versions (task_id);

CREATE INDEX ix_fanqie_task_aliases_task ON fanqie_promotion_task_aliases (task_id);

CREATE INDEX ix_fanqie_video_jobs_id ON fanqie_video_jobs (id);

CREATE INDEX ix_fanqie_video_jobs_job_uuid ON fanqie_video_jobs (job_uuid);

CREATE INDEX ix_fanqie_video_jobs_script_id ON fanqie_video_jobs (script_id);

CREATE INDEX ix_fanqie_video_jobs_status ON fanqie_video_jobs (status);

CREATE INDEX ix_fanqie_video_jobs_task_id ON fanqie_video_jobs (task_id);

CREATE UNIQUE INDEX uq_fanqie_bindings_publish_success
        ON fanqie_bindings(publish_id)
        WHERE status = 'bound'
    ;

CREATE UNIQUE INDEX uq_fanqie_chapters_book_idx ON fanqie_chapters (book_id, chapter_index);

CREATE UNIQUE INDEX uq_fanqie_perf_daily ON fanqie_performance_daily (publish_id, snapshot_date);

CREATE UNIQUE INDEX uq_fanqie_scripts_task_version ON fanqie_script_versions (task_id, version);

CREATE UNIQUE INDEX uq_fanqie_task_active_alias
        ON fanqie_promotion_tasks(book_id, promotion_alias)
        WHERE promotion_alias IS NOT NULL
          AND status NOT IN ('rejected', 'expired', 'completed', 'stopped', 'cancelled')
    ;
