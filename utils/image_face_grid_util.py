"""图片人脸网格商业能力的兼容调用门面。"""

from services import face_mask_provider

ConvertResult = face_mask_provider.ImageGridConvertResult


def convert_black_face_masks_to_red_grids(
    original_image_path: str,
    masked_image_path: str,
    output_image_path: str,
) -> ConvertResult:
    return face_mask_provider.convert_black_face_masks_to_red_grids(
        original_image_path,
        masked_image_path,
        output_image_path,
    )


__all__ = ["ConvertResult", "convert_black_face_masks_to_red_grids"]
