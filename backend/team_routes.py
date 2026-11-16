from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse

from . import teams


def create_router(current_user, current_admin, uploaded_bytes, upload_name):
    def build(admin, dependency):
        routes = APIRouter()

        @routes.get("")
        async def list_spaces(include_archived: bool = False, user=Depends(dependency)):
            return teams.list_spaces(user, include_archived, admin=admin)

        @routes.post("")
        async def create_space(request: Request, user=Depends(dependency)):
            return teams.create_space(user, await request.json(), admin=admin)

        @routes.get("/{space_id}")
        async def get_space(space_id: str, user=Depends(dependency)):
            return teams.get_space(user, space_id, admin=admin)

        @routes.patch("/{space_id}")
        async def update_space(space_id: str, request: Request, user=Depends(dependency)):
            return teams.update_space(user, space_id, await request.json(), admin=admin)

        @routes.delete("/{space_id}")
        async def archive_space(space_id: str, user=Depends(dependency)):
            return teams.archive_space(user, space_id, admin=admin)

        @routes.post("/{space_id}/restore")
        async def restore_space(space_id: str, user=Depends(dependency)):
            return teams.restore_space(user, space_id, admin=admin)

        @routes.post("/{space_id}/transfer")
        async def transfer_space(space_id: str, request: Request, user=Depends(dependency)):
            return teams.transfer_space(user, space_id, await request.json(), admin=admin)

        @routes.get("/{space_id}/members")
        async def list_members(space_id: str, user=Depends(dependency)):
            return teams.list_members(user, space_id, admin=admin)

        @routes.post("/{space_id}/members")
        async def add_member(space_id: str, request: Request, user=Depends(dependency)):
            return teams.add_member(user, space_id, await request.json(), admin=admin)

        @routes.patch("/{space_id}/members/{user_id}")
        async def update_member(space_id: str, user_id: str, request: Request, user=Depends(dependency)):
            return teams.update_member(user, space_id, user_id, await request.json(), admin=admin)

        @routes.delete("/{space_id}/members/{user_id}")
        async def remove_member(space_id: str, user_id: str, user=Depends(dependency)):
            return teams.remove_member(user, space_id, user_id, admin=admin)

        if not admin:
            @routes.post("/{space_id}/leave")
            async def leave_space(space_id: str, user=Depends(dependency)):
                return teams.remove_member(user, space_id, user["id"])

        @routes.get("/{space_id}/files")
        async def list_files(space_id: str, user=Depends(dependency)):
            return teams.list_files(user, space_id, admin=admin)

        @routes.post("/{space_id}/files")
        async def upload_file(space_id: str, file: UploadFile = File(...), user=Depends(dependency)):
            name = upload_name(file)
            content = await uploaded_bytes(file)
            return teams.upload_file(user, space_id, content, name, file.content_type, admin=admin)

        @routes.get("/{space_id}/files/{file_id}")
        async def get_file(space_id: str, file_id: str, user=Depends(dependency)):
            return teams.get_file(user, space_id, file_id, admin=admin)

        @routes.patch("/{space_id}/files/{file_id}")
        async def rename_file(space_id: str, file_id: str, request: Request, user=Depends(dependency)):
            return teams.rename_file(user, space_id, file_id, await request.json(), admin=admin)

        @routes.put("/{space_id}/files/{file_id}/content")
        async def replace_file(space_id: str, file_id: str, file: UploadFile = File(...), user=Depends(dependency)):
            content = await uploaded_bytes(file)
            return teams.replace_file(user, space_id, file_id, content, file.content_type, admin=admin)

        @routes.get("/{space_id}/files/{file_id}/download")
        async def download_file(space_id: str, file_id: str, user=Depends(dependency)):
            value, path = teams.download_file(user, space_id, file_id, admin=admin)
            return FileResponse(path, filename=value["name"], media_type="application/octet-stream")

        @routes.delete("/{space_id}/files/{file_id}")
        async def delete_file(space_id: str, file_id: str, user=Depends(dependency)):
            return teams.delete_file(user, space_id, file_id, admin=admin)

        return routes

    router = APIRouter()
    router.include_router(build(False, current_user), prefix="/api/team-spaces")
    router.include_router(build(True, current_admin), prefix="/api/admin/team-spaces")
    return router
