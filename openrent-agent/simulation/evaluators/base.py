from abc import ABC, abstractmethod


class BaseEvaluator(ABC):
    @abstractmethod
    def evaluate(self, transcript, context, actor, policy):
        raise NotImplementedError

