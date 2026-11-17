/* 医枢 · 云服务公开配置
   仅含可公开的客户端标识；publishableKey 本身不含权限，服务端按注册域名做 Origin 校验。
   真正的权限由登录后的 WorkBuddy 会话与云数据库 RLS(owner_id=auth.uid()) 决定。
   修改应用或重新发布后，如登录/同步报错，请用工作区最新的 publicConfig 更新本文件。 */
window.MEDNEXUS_CLOUD = {
  endpoint: "https://wbapp-kezc39fwxl8eeukjgjpg0d.app.workbuddy.host",
  oauthRelayBaseUrl: "https://www.workbuddy.cn/v2/as/genie-baas/oauth",
  publishableKey: "wbpk_KezC39fwXL8eeukjgJpg0d_9lpBYICBew7IEFfWdCbV0W4LVQojsnWV",
  appId: "wbapp_KezC39fwXL8eeukjgJpg0d"
};
