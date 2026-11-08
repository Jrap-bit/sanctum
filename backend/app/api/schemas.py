from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field



class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionInput(Input):
    expectedVersion: int = Field(ge=1)
