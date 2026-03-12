package com.it.config;

import io.netty.channel.ChannelOption;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;

@Configuration
@EnableConfigurationProperties(WebClientConfig.AiApiProperties.class)
@Slf4j
public class WebClientConfig {

    @Bean
    public WebClient webClient(AiApiProperties properties) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, properties.getConnectTimeout())
                .responseTimeout(Duration.ofMillis(properties.getReadTimeout()));

        String baseUrl = normalizeBaseUrl(properties.getUrl());
        log.info("AI WebClient baseUrl = {}", baseUrl);

        return WebClient.builder()
                .baseUrl(baseUrl)
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }

    private String normalizeBaseUrl(String url) {
        if (url == null) {
            return "http://localhost:8000";
        }
        String normalized = url.trim();
        while (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }

    @Data
    @ConfigurationProperties(prefix = "ai.api")
    public static class AiApiProperties {
        private String url = "http://localhost:8000";
        private int connectTimeout = 10000;
        private int readTimeout = 600000;
    }
}
