import { request } from '../request';

/** 图形验证码(FBA /auth/captcha:登录是否必须验证码以 is_enabled 为准) */
export function fetchCaptcha() {
  return request<Api.Auth.CaptchaInfo>({ url: '/auth/captcha', method: 'get' });
}

/** 登录(FBA:/auth/login,JSON,需验证码 uuid+captcha) */
export function fetchLogin(userName: string, password: string, captcha?: string, uuid?: string) {
  return request<Api.Auth.FbaLoginResult>({
    url: '/auth/login',
    method: 'post',
    data: {
      username: userName,
      password,
      uuid,
      captcha
    }
  });
}

/** 当前用户信息(FBA /sys/users/me) */
export function fetchGetUserInfo() {
  return request<Api.Auth.FbaUserInfo>({ url: '/sys/users/me' });
}

/** 刷新 token(FBA /auth/refresh,Bearer 换发) */
export function fetchRefreshToken(_refreshToken: string) {
  return request<{ access_token: string }>({ url: '/auth/refresh', method: 'post' });
}

/** 登出 */
export function fetchLogout() {
  return request<null>({ url: '/auth/logout', method: 'post' });
}

/** 授权码(可选;FBA /auth/codes) */
export function fetchGetAuthCodes() {
  return request<string[]>({ url: '/auth/codes' });
}
