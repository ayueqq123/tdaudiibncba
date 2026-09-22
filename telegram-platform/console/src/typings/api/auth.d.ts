declare namespace Api {
  /**
   * namespace Auth
   *
   * backend api module: "auth" (FBA)
   */
  namespace Auth {
    interface LoginToken {
      token: string;
      refreshToken: string;
    }

    interface UserInfo {
      userId: string;
      userName: string;
      roles: string[];
      buttons: string[];
    }

    /** FBA GET /auth/captcha */
    interface CaptchaInfo {
      is_enabled: boolean;
      expire_seconds: number;
      uuid: string;
      /** jpeg base64(无 data: 前缀) */
      image: string;
    }

    /** FBA POST /auth/login → data */
    interface FbaLoginResult {
      access_token: string;
      access_token_expire_time: string;
      session_uuid: string;
      user: Record<string, any>;
    }

    /** FBA GET /sys/users/me → data */
    interface FbaUserInfo {
      id: number;
      username: string;
      nickname: string | null;
      avatar: string | null;
      email: string | null;
      roles: string[];
      is_superuser: boolean;
      is_staff: boolean;
      status: number;
      dept?: string | null;
    }
  }
}
