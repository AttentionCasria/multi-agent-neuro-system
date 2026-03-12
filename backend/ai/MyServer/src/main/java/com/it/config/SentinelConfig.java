//package com.it.config;
//
//import com.alibaba.csp.sentinel.slots.block.RuleConstant;
//import com.alibaba.csp.sentinel.slots.block.flow.FlowRule;
//import com.alibaba.csp.sentinel.slots.block.flow.FlowRuleManager;
//import jakarta.annotation.PostConstruct;
//import org.springframework.context.annotation.Configuration;
//
//import java.util.ArrayList;
//import java.util.List;
//
//@Configuration
//public class SentinelConfig {
//
//    @PostConstruct
//    public void initSentinelRules() {
//        List<FlowRule> rules = new ArrayList<>();
//
//        // 1. 登录限流规则
//        FlowRule loginRule = new FlowRule();
//        loginRule.setResource("LoginController:login");
//        loginRule.setGrade(RuleConstant.FLOW_GRADE_QPS);
//        loginRule.setCount(20); // 每秒最多20次登录
//        rules.add(loginRule);
//
//        // 2. SSE 接口限流规则 (由于是长连接，QPS设置宜小不宜大)
//        FlowRule sseRule = new FlowRule();
//        sseRule.setResource("QuesController:streamingQues");
//        sseRule.setGrade(RuleConstant.FLOW_GRADE_QPS);
//        sseRule.setCount(10); // 每秒最多允许10个新连接进入
//        rules.add(sseRule);
//
//        // 3. 注册限流规则
//        FlowRule registerRule = new FlowRule();
//        registerRule.setResource("LoginController:register");
//        registerRule.setGrade(RuleConstant.FLOW_GRADE_QPS);
//        registerRule.setCount(10); // 每秒最多10次注册，比登录更严格
//        rules.add(registerRule);
//
//        // 加载规则
//        FlowRuleManager.loadRules(rules);
//    }
//}