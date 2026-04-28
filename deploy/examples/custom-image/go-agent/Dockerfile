FROM golang:1.23-alpine AS builder
WORKDIR /src
COPY main.go .
RUN go mod init example.com/custom-agent && go build -o /agent .

FROM alpine:3.20
COPY --from=builder /agent /agent
EXPOSE 8080
CMD ["/agent"]
