package com.it.interceptor;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.util.StrUtil;
import com.it.po.dto.UserDTO;
import com.it.utils.JWT;
import com.it.utils.ThreadLocalUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.servlet.HandlerInterceptor;

import java.util.Map;
import java.util.concurrent.TimeUnit;

@Slf4j
public class RefreshTokenInterceptor implements HandlerInterceptor {

    private final StringRedisTemplate stringRedisTemplate;

    public RefreshTokenInterceptor(StringRedisTemplate stringRedisTemplate) {
        this.stringRedisTemplate = stringRedisTemplate;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        String token = resolveToken(request);
        if (StrUtil.isBlank(token)) {
            return true;
        }

        try {
            Long userId = JWT.getUserIdFromToken(token);

            Object jtiObj = JWT.parseToken(token).get("jti");
            if (jtiObj == null) {
                log.warn("Token 中缺少 jti，可能是旧 Token");
                sendUnauthorized(response, "Token 已过期，请重新登录");
                return false;
            }
            String tokenJti = jtiObj.toString();

            String redisJti = stringRedisTemplate.opsForValue().get("login:user:" + userId);
            if (redisJti == null) {
                log.warn("用户 {} 在 Redis 中没有登录记录，可能是 Token 过期了", userId);
                sendUnauthorized(response, "Token 已过期，请重新登录");
                return false;
            }

            if (!redisJti.equals(tokenJti)) {
                log.warn("用户 {} 在其他地方登录了，当前 Token 已失效", userId);
                sendUnauthorized(response, "您的账号已在其他地方登录，请重新登录");
                return false;
            }

            Map<Object, Object> userMap = stringRedisTemplate.opsForHash().entries("user:token:" + token);
            if (userMap.isEmpty()) {
                log.warn("Token 在 Redis 中未找到用户会话: userId={}", userId);
                sendUnauthorized(response, "登录状态已失效，请重新登录");
                return false;
            }

            UserDTO userDTO = BeanUtil.fillBeanWithMap(userMap, new UserDTO(), false);
            ThreadLocalUtil.setCurrentUser(userDTO);
            stringRedisTemplate.expire("user:token:" + token, 30, TimeUnit.MINUTES);

        } catch (Exception e) {
            log.error("Token 解析失败: {}", e.getMessage());
            sendUnauthorized(response, "Token 解析失败，请重新登录");
            return false;
        }
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) {
        ThreadLocalUtil.removeCurrentUser();
    }

    private String resolveToken(HttpServletRequest request) {
        String token = request.getHeader("token");
        if (StrUtil.isNotBlank(token)) {
            return token.trim();
        }
        String authorization = request.getHeader("Authorization");
        if (StrUtil.isBlank(authorization)) {
            return null;
        }
        authorization = authorization.trim();
        return authorization.startsWith("Bearer ") ? authorization.substring(7).trim() : authorization;
    }

    private void sendUnauthorized(HttpServletResponse response, String msg) throws Exception {
        response.setContentType("application/json;charset=UTF-8");
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.getWriter().write("{\"code\": 401, \"msg\": \"" + msg + "\"}");
    }
}