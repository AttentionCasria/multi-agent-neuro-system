package com.it.interceptor;

import com.it.utils.ThreadLocalUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.servlet.HandlerInterceptor;

@Slf4j
public class Tokeninterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        // 打印当前拦截到的路径，看看是不是登录路径没被排除掉
        String uri = request.getRequestURI();
        log.info("当前拦截到的路径：{}", uri);

        // 记录请求 IP 到 ThreadLocal，供后续服务线程读取（避免 reactive 中 RequestContextHolder 为空）
        String ip = request.getHeader("X-Forwarded-For");
        if (ip == null || ip.isEmpty()) {
            ip = request.getRemoteAddr();
        }
        ThreadLocalUtil.setCurrentIp(ip);

        // 打印请求中的 token（如果有）或 Authorization，便于排查前端 header 名称不一致问题
        String tokenHeader = request.getHeader("token");
        String authHeader = request.getHeader("Authorization");

        if (tokenHeader != null) log.debug("请求 token header: {}", tokenHeader);
        if (authHeader != null) log.debug("请求 Authorization header: {}", authHeader);

        // 放行匿名接口（注册、登录、退出），避免拦截器阻断这些请求
        // 注意：根据你项目的路由，这里列出常见需要放行的 URL
        if (uri.startsWith("/api/user/register") || uri.startsWith("/api/user/login") || uri.startsWith("/api/user/logOut")) {
            log.debug("放行公共接口：{}", uri);
            return true;
        }

        // 直接看 ThreadLocalUtil 里有没有用户对象
        if (ThreadLocalUtil.getCurrentUser() == null) {
            log.info("用户未登录，拒绝访问");
            response.setStatus(401);
            return false;
        }
        return true; // 有用户，放行
    }

    // 确保在请求完成后清理 ThreadLocal，避免内存泄漏或跨请求污染
    @Override
    public void afterCompletion(HttpServletRequest request,
                                HttpServletResponse response,
                                Object handler, Exception ex) {
        try {
            ThreadLocalUtil.removeCurrentUser();
            ThreadLocalUtil.removeCurrentIp();
        } catch (Exception e) {
            log.warn("清理 ThreadLocal 失败: {}", e.getMessage(), e);
        }
    }
}