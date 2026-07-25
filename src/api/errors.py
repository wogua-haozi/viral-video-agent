from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(message)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message},
    )


ERROR_MESSAGES = {
    "AUTH_REQUIRED": "登录已过期，请重新登录。",
    "FORBIDDEN": "你没有权限访问该资源。",
    "JOB_NOT_FOUND": "未找到该分析任务。",
    "JOB_CANCELLED": "任务已取消。",
    "BILIBILI_UNAVAILABLE": "B站数据服务暂时不可用，请稍后重试。",
    "NO_VIDEO_RESULTS": "没有找到足够的B站视频样本，请尝试更换赛道关键词。",
    "LLM_RATE_LIMITED": "模型服务繁忙，任务将稍后重试。",
    "LLM_AUTH_FAILED": "模型服务认证失败，请联系管理员检查配置。",
    "LLM_TIMEOUT": "模型响应超时，请稍后重试。",
    "ASR_UNAVAILABLE": "语音转写当前不可用，已降级为元数据分析。",
    "ASR_FILE_TOO_LARGE": "音频文件超过转写大小限制。",
    "ASR_FAILED": "语音转写失败，已降级为元数据分析。",
    "AUDIO_EXTRACTION_FAILED": "无法提取该视频音频，已跳过内容深度分析。",
    "EVIDENCE_INSUFFICIENT": "当前样本不足以支持完整结论。",
    "REPORT_VALIDATION_FAILED": "报告引用校验失败，未发布未经支持的结论。",
    "WORKER_FAILED": "后台任务执行失败，请重试。",
    "JOB_NOT_RETRYABLE": "当前任务状态不能重试。",
    "CLARIFICATION_NOT_FOUND": "当前任务没有待回答的澄清问题。",
    "CLARIFICATION_CONFLICT": "该澄清请求已经用不同答案提交。",
    "CLARIFICATION_INVALID": "澄清回答无效或已过期。",
    "JOB_REVISION_INVALID": "当前任务仍在执行，请先取消后再修改研究范围。",
    "JOB_REVISION_CONFLICT": "该修订请求与已存在的任务不一致。",
    "JOB_HAS_REVISIONS": "该任务已有修订记录，不能删除审计来源。",
    "CANDIDATE_SNAPSHOT_NOT_FOUND": "候选快照不存在或已过期。",
    "CANDIDATE_DECISION_INVALID": "候选确认内容不完整或无效。",
    "CANDIDATE_DECISION_CONFLICT": "该候选确认请求已用不同内容提交。",
    "CANDIDATE_DECISION_ALREADY_SUBMITTED": "该候选快照已经完成确认。",
    "CANDIDATE_EVIDENCE_INSUFFICIENT": "当前 Evidence 中没有足够的稳定账号身份，无法进入候选确认。",
    "CANDIDATE_SNAPSHOT_INVALID": "候选快照校验失败，未继续生成报告。",
    "REQUEST_BODY_TOO_LARGE": "候选确认请求体过大。",
}
