declare namespace Api {
  /** TG 业务域(FBA /api/v1/tg/*) */
  namespace Tg {
    interface Tenant {
      id: number;
      uuid: string;
      name: string;
      status: number;
      remark: string | null;
      created_time: string;
    }

    interface Project {
      id: number;
      uuid: string;
      tenant_id: number;
      name: string;
      status: number;
      remark: string | null;
      created_time: string;
    }

    interface Account {
      id: number;
      uuid: string;
      tenant_id: number;
      project_id: number;
      import_batch_id: number | null;
      telegram_user_id: number | null;
      phone: string | null;
      username: string | null;
      desired_status: string;
      observed_status: string;
      remark: string | null;
      created_time: string;
    }

    interface ImportBatch {
      id: number;
      uuid: string;
      tenant_id: number;
      project_id: number;
      status: string;
      total: number;
      verified_count?: number;
      created_time: string;
      results?: ImportBatchItem[];
    }

    interface ImportBatchItem {
      phone?: string;
      telegram_user_id?: number;
      grade: string;
      reason?: string;
    }

    type CloneMode = 'copy' | 'forward';

    interface CloneTarget {
      id: number;
      route_id: string;
      rule_id: number;
      source_chat_id: number;
      source_topic_id: number | null;
      target_chat_id: number;
      target_topic_id: number | null;
      filters: Record<string, any> | null;
      status: string;
      remark: string | null;
      created_time: string;
    }

    interface CloneRule {
      id: number;
      uuid: string;
      tenant_id: number;
      project_id: number;
      account_id: number;
      name: string;
      mode: CloneMode;
      enabled: boolean;
      current_version: number;
      status: string;
      remark: string | null;
      created_time: string;
      updated_time: string | null;
      targets?: CloneTarget[];
    }

    interface CloneRuleVersion {
      id: number;
      rule_id: number;
      version: number;
      snapshot: Record<string, any>;
      published_by: number;
      published_at: string;
    }

    interface DeliveryJob {
      id: string;
      kind: string;
      route_id: string;
      rule_id: string;
      rule_version: number;
      account_id: string;
      source_scope: string;
      source_chat_id: number;
      source_message_id: number;
      target_chat_id: number;
      mode: string;
      status: string;
      attempt_count: number;
      next_attempt_at: string | null;
      flood_wait_until: string | null;
      last_error_class: string | null;
      created_at: string | null;
      attempts?: DeliveryAttempt[];
    }

    interface DeliveryAttempt {
      id: string;
      attempt_no: number;
      worker_generation: number;
      started_at: string | null;
      finished_at: string | null;
      result_status: string | null;
      error_class: string | null;
    }

    interface ReplyCandidate {
      id: number;
      uuid: string;
      tenant_id: number;
      project_id: number;
      account_id: number;
      target_chat_id: number;
      content: string;
      content_hash: string;
      version: number;
      status: string;
      expires_at: string;
      created_time: string;
    }

    interface Approval {
      id: number;
      uuid: string;
      tenant_id: number;
      project_id: number;
      candidate_id: number;
      candidate_version: number;
      content_hash: string;
      status: string;
      reason: string | null;
      decided_at: string | null;
      expires_at: string;
      created_time: string;
    }

    type RuntimeCommandType =
      | 'StartAccount'
      | 'StopAccount'
      | 'ReloadConfig'
      | 'SyncChats'
      | 'ReconcileSource'
      | 'CancelJob';

    interface RuntimeCommand {
      id: number;
      uuid: string;
      dedup_key: string;
      tenant_id: number;
      project_id: number;
      account_id: number;
      type: string;
      status: string;
      payload: Record<string, any> | null;
      result: string | null;
      issued_by: number;
      deadline: string | null;
      acked_at: string | null;
      created_time: string;
    }
  }
}
